from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from vllm_request_lifecycle_profiler.kv_recovery_profile_protocol import (
    KVRecoveryProfileConfig,
)
from vllm_request_lifecycle_profiler.kv_recovery_runtime import (
    BaseEventRef,
    BoundedKVRecoveryProfileLedger,
    ExpectedH2DRecovery,
    KVRecoveryObserverFactoryAdapter,
    KVRecoveryRuntimeABI,
    KVRecoverySchedulerAdapter,
    KVRecoveryWorkerEvidenceAdapter,
    RequestLifecycleIdentity,
    RuntimeBaseLifecycleBridge,
    normalize_h2d_recovery,
)
from vllm_request_lifecycle_profiler.runtime_hooks import (
    JsonlTraceSink,
    RuntimeLifecycleHooks,
    RuntimeTraceConfig,
)
from vllm_request_lifecycle_profiler.runtime_protocol import (
    KV_RECOVERY_COMMUNICATION_MODE,
    EventDraft,
    RuntimeProvenance,
)

WORKER_UUID = "1" * 32
ENGINE_UUID = "2" * 32
CLOCK_DOMAIN_ID = "3" * 32
RUN_ID = "4" * 32
TRACE_ID = "5" * 32
RUNTIME_REQUEST_ID = "request-0"
PREEMPTED_EVENT_ID = f"{ENGINE_UUID}:e:0"
ADMISSION_STARTED_EVENT_ID = f"{ENGINE_UUID}:e:1"
RESUMED_EVENT_ID = f"{ENGINE_UUID}:e:2"
FIRST_COMPUTE_EVENT_ID = f"{ENGINE_UUID}:e:3"
PROVENANCE = RuntimeProvenance("a" * 40, "b" * 40, "c" * 40)


@dataclass(frozen=True)
class FakeCoordinate:
    group_index: int
    logical_ordinal: int


@dataclass(frozen=True)
class FakeIdentity:
    run_id: str
    trace_id: str
    engine_lifecycle_id: str
    runtime_request_id: str
    recovery_epoch: int | None
    episode_id: str | None
    base_preempted_event_id: str | None
    preempt_profile_record_id: str | None


@dataclass(frozen=True)
class FakeLogicalBlock:
    group_index: int
    logical_ordinal: int
    logical_block_id: str


@dataclass(frozen=True)
class FakeContext:
    identity: FakeIdentity
    operation: str
    block_set_id: str
    logical_blocks: tuple[FakeLogicalBlock, ...]


@dataclass(frozen=True)
class FakeAttempt:
    connector_job_id: int
    transfer_id: str
    context: FakeContext


@dataclass(frozen=True)
class FakeComputeContext:
    identity: FakeIdentity
    transfer_id: str
    block_set_id: str
    bytes_moved: int
    admission_profile_record_id: str
    compute_kind: str
    base_phase_start_event_id: str


@dataclass(frozen=True)
class FakeReceipt:
    connector_job_id: int
    transfer_id: str
    identity: FakeIdentity
    block_set_id: str
    process_uuid: str
    rank: int
    world_size: int
    clock_domain_id: str
    communication_done_event_id: str
    restore_done_profile_record_id: str
    timestamp_ns: int
    bytes_moved: int


class FakeBoundedWorkerObserver:
    def __init__(self, process_uuid, run_id, clock_domain_id, sink) -> None:
        self.process_uuid = process_uuid
        self.run_id = run_id
        self.clock_domain_id = clock_domain_id
        self.sink = sink


def canonical_block_set_id(
    identity: FakeIdentity,
    blocks: tuple[FakeLogicalBlock, ...],
) -> str:
    rows = "".join(
        f"{block.group_index}:{block.logical_ordinal}:{block.logical_block_id}\n"
        for block in blocks
    )
    prefix = (
        f"rlp.kv-recovery/v1alpha1\0{identity.run_id}\0{identity.engine_lifecycle_id}\0"
    )
    return hashlib.sha256(f"{prefix}{rows}".encode()).hexdigest()


FAKE_ABI = KVRecoveryRuntimeABI(
    identity_type=FakeIdentity,
    logical_block_type=FakeLogicalBlock,
    transfer_context_type=FakeContext,
    compute_context_type=FakeComputeContext,
    receipt_type=FakeReceipt,
    bounded_worker_observer_type=FakeBoundedWorkerObserver,
    canonical_block_set_id=canonical_block_set_id,
)


class FakeBridge:
    def request_identity(
        self, runtime_request_id: str
    ) -> RequestLifecycleIdentity | None:
        if runtime_request_id != RUNTIME_REQUEST_ID:
            return None
        return RequestLifecycleIdentity(
            trace_id=TRACE_ID,
            engine_lifecycle_id=f"{TRACE_ID}:e:0",
            runtime_request_id=runtime_request_id,
        )

    def preempted_event(
        self, runtime_request_id: str, recovery_epoch: int
    ) -> BaseEventRef | None:
        if runtime_request_id == RUNTIME_REQUEST_ID and recovery_epoch == 1:
            return BaseEventRef(PREEMPTED_EVENT_ID, 90)
        return None

    def admission_started_event(
        self, runtime_request_id: str, recovery_epoch: int
    ) -> BaseEventRef | None:
        if runtime_request_id == RUNTIME_REQUEST_ID and recovery_epoch == 1:
            return BaseEventRef(ADMISSION_STARTED_EVENT_ID, 130)
        return None

    def resumed_event(
        self, runtime_request_id: str, recovery_epoch: int
    ) -> BaseEventRef | None:
        if runtime_request_id == RUNTIME_REQUEST_ID and recovery_epoch == 1:
            return BaseEventRef(RESUMED_EVENT_ID, 140)
        return None

    def first_compute_event(
        self, runtime_request_id: str, recovery_epoch: int
    ) -> BaseEventRef | None:
        if runtime_request_id == RUNTIME_REQUEST_ID and recovery_epoch == 1:
            return BaseEventRef(FIRST_COMPUTE_EVENT_ID, 150)
        return None

    def emit_first_compute(
        self,
        runtime_request_id: str,
        recovery_epoch: int,
        *,
        timestamp_ns: int,
        compute_kind: str,
    ) -> BaseEventRef | None:
        if (
            runtime_request_id == RUNTIME_REQUEST_ID
            and recovery_epoch == 1
            and timestamp_ns >= 140
            and compute_kind in {"prefill", "decode"}
        ):
            return BaseEventRef(FIRST_COMPUTE_EVENT_ID, timestamp_ns)
        return None


def make_hooks(tmp_path: Path) -> RuntimeLifecycleHooks:
    sink = JsonlTraceSink(
        tmp_path / "trace",
        PROVENANCE,
        communication_mode=KV_RECOVERY_COMMUNICATION_MODE,
        kv_recovery_profile_config=KVRecoveryProfileConfig(run_id=RUN_ID),
        clock_ns=lambda: 1000,
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: WORKER_UUID,
    )
    # Environment-derived construction remains disabled for every non-none
    # mode.  Injecting this exact sink is an isolated source-conformance seam.
    return RuntimeLifecycleHooks(
        RuntimeTraceConfig(
            export_path=tmp_path / "trace",
            provenance=PROVENANCE,
            communication_mode=KV_RECOVERY_COMMUNICATION_MODE,
            kv_recovery_profile_config=KVRecoveryProfileConfig(run_id=RUN_ID),
        ),
        sink=sink,
    )


def read_committed_records(hooks: RuntimeLifecycleHooks) -> list[dict[str, object]]:
    result = hooks.close()
    assert result is not None
    assert result.close_outcome == "drained"
    path = hooks.committed_shard_path
    assert path is not None
    return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.mark.parametrize(
    "runtime_request_id",
    ["请求-1", "", "x" * 129, "line\nbreak"],
)
def test_runtime_bridge_rejects_invalid_request_id_without_emitting(
    tmp_path: Path,
    runtime_request_id: str,
) -> None:
    hooks = make_hooks(tmp_path)
    bridge = RuntimeBaseLifecycleBridge(hooks)

    assert not bridge.register_runtime_request(
        RUN_ID, runtime_request_id, timestamp_ns=1
    )
    records = read_committed_records(hooks)

    assert not any(row.get("record_type") == "event" for row in records)


@pytest.mark.parametrize(
    ("terminal_cause", "event_name"),
    [
        ("complete", "generation_done"),
        ("explicit_cancel", "aborted"),
        ("client_disconnect", "cancelled"),
        ("client_timeout", "cancelled"),
        ("engine_failure", "error"),
    ],
)
def test_runtime_bridge_emits_exactly_one_terminal(
    tmp_path: Path,
    terminal_cause: str,
    event_name: str,
) -> None:
    hooks = make_hooks(tmp_path)
    bridge = RuntimeBaseLifecycleBridge(hooks)
    assert bridge.register_runtime_request(RUN_ID, RUNTIME_REQUEST_ID, timestamp_ns=1)
    if terminal_cause == "complete":
        assert bridge.emit_runtime_scheduled(
            RUNTIME_REQUEST_ID,
            timestamp_ns=2,
            compute_kind="decode",
            scheduled_tokens=1,
            prompt_tokens_total=2,
            prompt_tokens_cached=1,
        )

    terminal = bridge.emit_runtime_terminal(
        RUNTIME_REQUEST_ID,
        terminal_cause,
        timestamp_ns=3,
        generated_tokens_total=3,
    )
    duplicate = bridge.emit_runtime_terminal(
        RUNTIME_REQUEST_ID,
        terminal_cause,
        timestamp_ns=4,
        generated_tokens_total=3,
    )
    records = read_committed_records(hooks)

    assert terminal is not None
    assert duplicate is None
    terminals = [
        row
        for row in records
        if row.get("record_type") == "event" and row.get("event_name") == event_name
    ]
    assert len(terminals) == 1
    assert terminals[0]["metadata"]["terminal_cause"] == terminal_cause
    if terminal_cause == "complete":
        assert any(
            row.get("record_type") == "event" and row.get("event_name") == "decode_done"
            for row in records
        )


def test_runtime_bridge_closes_prefill_before_decode_and_completion(
    tmp_path: Path,
) -> None:
    hooks = make_hooks(tmp_path)
    bridge = RuntimeBaseLifecycleBridge(hooks)
    assert bridge.register_runtime_request(RUN_ID, RUNTIME_REQUEST_ID, timestamp_ns=1)
    assert bridge.emit_runtime_scheduled(
        RUNTIME_REQUEST_ID,
        timestamp_ns=2,
        compute_kind="prefill",
        scheduled_tokens=2,
        prompt_tokens_total=4,
        prompt_tokens_cached=1,
    )
    assert bridge.emit_runtime_scheduled(
        RUNTIME_REQUEST_ID,
        timestamp_ns=3,
        compute_kind="decode",
        scheduled_tokens=1,
        prompt_tokens_total=4,
        prompt_tokens_cached=1,
    )
    assert bridge.emit_runtime_terminal(
        RUNTIME_REQUEST_ID,
        "complete",
        timestamp_ns=4,
        generated_tokens_total=1,
    )

    records = read_committed_records(hooks)
    event_names = [
        row["event_name"] for row in records if row.get("record_type") == "event"
    ]
    assert event_names == [
        "queued",
        "scheduled",
        "prefill_started",
        "prefill_done",
        "decode_started",
        "decode_done",
        "generation_done",
    ]


def test_scheduler_adapter_emits_terminal_in_engine_process_trace(
    tmp_path: Path,
) -> None:
    hooks = make_hooks(tmp_path)
    profile = BoundedKVRecoveryProfileLedger(ENGINE_UUID)
    scheduler = KVRecoverySchedulerAdapter(
        RUN_ID,
        hooks,
        profile,
        RuntimeBaseLifecycleBridge(hooks),
        FAKE_ABI,
        clock_ns=iter((1, 2, 3)).__next__,
    )

    scheduler.request_started(RUNTIME_REQUEST_ID)
    scheduler.request_scheduled(RUNTIME_REQUEST_ID, "decode", 1, 2, 1)
    scheduler.request_terminal(RUNTIME_REQUEST_ID, "complete", 1)

    records = read_committed_records(hooks)
    event_names = [
        row["event_name"] for row in records if row.get("record_type") == "event"
    ]
    assert event_names == [
        "queued",
        "scheduled",
        "decode_started",
        "decode_done",
        "generation_done",
    ]
    assert profile.evidence_complete


def test_distinct_recovery_epochs_do_not_invalidate_each_other(tmp_path: Path) -> None:
    class MultiEpochBridge(FakeBridge):
        def preempted_event(
            self, runtime_request_id: str, recovery_epoch: int
        ) -> BaseEventRef | None:
            if runtime_request_id != RUNTIME_REQUEST_ID:
                return None
            return BaseEventRef(f"{ENGINE_UUID}:e:{recovery_epoch + 10}", 90)

    hooks = make_hooks(tmp_path)
    profile = BoundedKVRecoveryProfileLedger(ENGINE_UUID)
    scheduler = KVRecoverySchedulerAdapter(
        RUN_ID,
        hooks,
        profile,
        MultiEpochBridge(),
        FAKE_ABI,
        clock_ns=lambda: 100,
    )

    assert scheduler.request_preempted(RUNTIME_REQUEST_ID, 1) is not None
    assert scheduler.request_preempted(RUNTIME_REQUEST_ID, 2) is not None

    records, losses = profile.snapshot()
    assert records == ()
    assert losses == ()


def test_runtime_bridge_continues_compute_and_terminal_after_recovery(
    tmp_path: Path,
) -> None:
    hooks = make_hooks(tmp_path)
    bridge = RuntimeBaseLifecycleBridge(hooks)

    assert bridge.register_runtime_request(RUN_ID, RUNTIME_REQUEST_ID, timestamp_ns=1)
    assert bridge.emit_runtime_scheduled(
        RUNTIME_REQUEST_ID,
        timestamp_ns=2,
        compute_kind="prefill",
        scheduled_tokens=2,
        prompt_tokens_total=4,
        prompt_tokens_cached=0,
    )
    assert bridge.emit_runtime_preempted(RUNTIME_REQUEST_ID, 1, timestamp_ns=3)
    assert bridge.emit_runtime_admission_started(RUNTIME_REQUEST_ID, 1, timestamp_ns=4)
    assert bridge.emit_runtime_resumed(
        RUNTIME_REQUEST_ID,
        1,
        timestamp_ns=5,
        prompt_tokens_total=4,
        prompt_tokens_cached=3,
    )
    assert bridge.emit_first_compute(
        RUNTIME_REQUEST_ID, 1, timestamp_ns=6, compute_kind="prefill"
    )
    assert bridge.emit_runtime_scheduled(
        RUNTIME_REQUEST_ID,
        timestamp_ns=7,
        compute_kind="decode",
        scheduled_tokens=1,
        prompt_tokens_total=4,
        prompt_tokens_cached=4,
    )
    assert bridge.emit_runtime_terminal(
        RUNTIME_REQUEST_ID,
        "complete",
        timestamp_ns=8,
        generated_tokens_total=1,
    )

    records = read_committed_records(hooks)
    event_names = [
        row["event_name"] for row in records if row.get("record_type") == "event"
    ]
    assert event_names[-4:] == [
        "prefill_done",
        "decode_started",
        "decode_done",
        "generation_done",
    ]
    recovered_events = [
        row
        for row in records
        if row.get("event_name")
        in {
            "resumed",
            "prefill_done",
            "decode_started",
            "decode_done",
            "generation_done",
        }
    ]
    assert {row["preemption_epoch"] for row in recovered_events} == {1}
    summary = records[-1]
    assert summary["dropped_data_count"] == 0
    assert summary["writer_failure_count"] == 0


def base_endpoint_records() -> list[dict[str, object]]:
    return [
        {
            "record_type": "event",
            "event_id": PREEMPTED_EVENT_ID,
            "event_name": "preempted",
            "trace_id": TRACE_ID,
            "lifecycle_id": f"{TRACE_ID}:e:0",
            "preemption_epoch": 0,
            "timestamp_ns": 90,
        },
        {
            "record_type": "event",
            "event_id": ADMISSION_STARTED_EVENT_ID,
            "event_name": "admission_started",
            "trace_id": TRACE_ID,
            "lifecycle_id": f"{TRACE_ID}:e:0",
            "preemption_epoch": 1,
            "timestamp_ns": 130,
        },
        {
            "record_type": "event",
            "event_id": RESUMED_EVENT_ID,
            "event_name": "resumed",
            "trace_id": TRACE_ID,
            "lifecycle_id": f"{TRACE_ID}:e:0",
            "preemption_epoch": 1,
            "timestamp_ns": 140,
        },
    ]


def run_complete_episode(tmp_path: Path):
    hooks = make_hooks(tmp_path)
    worker_profile = BoundedKVRecoveryProfileLedger(WORKER_UUID)
    engine_profile = BoundedKVRecoveryProfileLedger(ENGINE_UUID)
    bridge = FakeBridge()
    scheduler = KVRecoverySchedulerAdapter(
        RUN_ID, hooks, engine_profile, bridge, FAKE_ABI, clock_ns=lambda: 125
    )
    worker = KVRecoveryWorkerEvidenceAdapter(hooks, worker_profile, FAKE_ABI, RUN_ID)

    scheduler.request_preempted(RUNTIME_REQUEST_ID, 1)
    context = scheduler.prepare_transfer_context(
        RUNTIME_REQUEST_ID,
        "h2d_restore",
        (FakeCoordinate(0, 0), FakeCoordinate(0, 1)),
    )
    assert isinstance(context, FakeContext)
    attempt = FakeAttempt(7, f"{WORKER_UUID}:t:0", context)
    worker.transfer_submitted(attempt, 100)
    receipt = worker.transfer_completed(
        attempt,
        submit_timestamp_ns=100,
        timestamp_ns=120,
        success=True,
        bytes_moved=256,
        device_duration_ns=10,
    )
    assert isinstance(receipt, FakeReceipt)
    scheduler.consume_h2d_receipts((receipt,), False)
    scheduler.request_admission_started(RUNTIME_REQUEST_ID, 1)
    scheduler.request_requeued(RUNTIME_REQUEST_ID, 1, "token_budget")
    compute_context = scheduler.request_admitted(RUNTIME_REQUEST_ID, 1, "prefill")
    assert isinstance(compute_context, FakeComputeContext)
    worker.first_compute(compute_context, 150)
    records = base_endpoint_records() + read_committed_records(hooks)
    expected = ExpectedH2DRecovery(
        trace_id=TRACE_ID,
        engine_lifecycle_id=f"{TRACE_ID}:e:0",
        recovery_epoch=1,
        transfer_id=attempt.transfer_id,
        block_set_id=context.block_set_id,
        preempted_event_id=PREEMPTED_EVENT_ID,
        admission_started_event_id=ADMISSION_STARTED_EVENT_ID,
    )
    return records, expected, worker_profile, engine_profile, receipt


def test_complete_cpu_adapter_chain_emits_exact_h2d_pair_and_three_edges(
    tmp_path: Path,
) -> None:
    records, expected, worker_profile, engine_profile, _receipt = run_complete_episode(
        tmp_path
    )

    normalized = normalize_h2d_recovery(
        records,
        expected,
        profile_evidence_complete=(
            worker_profile.evidence_complete and engine_profile.evidence_complete
        ),
    )

    assert normalized.duration_ns == 20
    assert normalized.bytes_moved == 256
    assert len(normalized.edge_ids) == 3
    worker_records, worker_losses = worker_profile.snapshot()
    engine_records, engine_losses = engine_profile.snapshot()
    assert worker_losses == ()
    assert engine_losses == ()
    assert [record.fields.get("stage") for record in worker_records] == [
        None,
        "restore_start",
        None,
        "restore_done",
        "first_prefill_or_decode",
    ]
    assert [record.fields.get("stage") for record in engine_records] == [
        "preempt",
        None,
        "scheduler_wakeup",
        "requeue",
        "admission",
    ]


def test_prepared_transfer_rejected_before_submit_is_not_profile_loss(
    tmp_path: Path,
) -> None:
    hooks = make_hooks(tmp_path)
    profile = BoundedKVRecoveryProfileLedger(WORKER_UUID)
    worker = KVRecoveryWorkerEvidenceAdapter(hooks, profile, FAKE_ABI, RUN_ID)
    context = FakeContext(
        identity=FakeIdentity(
            run_id=RUN_ID,
            trace_id=TRACE_ID,
            engine_lifecycle_id=f"{TRACE_ID}:e:0",
            runtime_request_id=RUNTIME_REQUEST_ID,
            recovery_epoch=None,
            episode_id=None,
            base_preempted_event_id=None,
            preempt_profile_record_id=None,
        ),
        operation="d2h_preserve",
        block_set_id="6" * 64,
        logical_blocks=(),
    )
    attempt = FakeAttempt(7, f"{WORKER_UUID}:t:0", context)

    worker.transfer_not_submitted(attempt)

    records, losses = profile.snapshot()
    assert records == ()
    assert losses == ()
    assert profile.attempted_data_count == 0
    assert profile.evidence_complete


def test_late_receipt_capacity_keeps_prefix_and_forbids_return_edge(
    tmp_path: Path,
) -> None:
    hooks = make_hooks(tmp_path)
    worker_profile = BoundedKVRecoveryProfileLedger(WORKER_UUID)
    engine_profile = BoundedKVRecoveryProfileLedger(ENGINE_UUID)
    scheduler = KVRecoverySchedulerAdapter(
        RUN_ID,
        hooks,
        engine_profile,
        FakeBridge(),
        FAKE_ABI,
        clock_ns=lambda: 125,
    )
    worker = KVRecoveryWorkerEvidenceAdapter(hooks, worker_profile, FAKE_ABI, RUN_ID)
    scheduler.request_preempted(RUNTIME_REQUEST_ID, 1)
    context = scheduler.prepare_transfer_context(
        RUNTIME_REQUEST_ID, "h2d_restore", (FakeCoordinate(0, 0),)
    )
    assert isinstance(context, FakeContext)
    attempt = FakeAttempt(9, f"{WORKER_UUID}:t:0", context)
    worker.transfer_submitted(attempt, 100)
    receipt = worker.transfer_completed(attempt, 100, 120, True, 128, None)
    assert isinstance(receipt, FakeReceipt)

    worker.h2d_receipt_capacity_exhausted(receipt, "serialization_failure")
    records = read_committed_records(hooks)

    communication_events = [
        row
        for row in records
        if row.get("event_name") in {"communication_started", "communication_done"}
    ]
    edges = [row for row in records if row.get("record_type") == "edge"]
    assert len(communication_events) == 2
    assert len(edges) == 2
    assert all(row.get("to_event_id") != ADMISSION_STARTED_EVENT_ID for row in edges)
    _profile_records, losses = worker_profile.snapshot()
    assert len(losses) == 1
    assert losses[0].reason == "serialization_failure"
    assert losses[0].counts["recovery_event"] == 1
    assert not worker_profile.evidence_complete


def test_normalizer_rejects_missing_duplicate_and_profile_loss(tmp_path: Path) -> None:
    records, expected, worker_profile, engine_profile, _receipt = run_complete_episode(
        tmp_path
    )
    assert worker_profile.evidence_complete and engine_profile.evidence_complete
    edges = [row for row in records if row.get("record_type") == "edge"]
    assert len(edges) == 3

    with pytest.raises(ValueError, match="missing or duplicated"):
        normalize_h2d_recovery(
            [row for row in records if row is not edges[-1]],
            expected,
            profile_evidence_complete=True,
        )
    with pytest.raises(ValueError, match="missing or duplicated"):
        normalize_h2d_recovery(
            [*records, dict(edges[-1], edge_id=f"{WORKER_UUID}:g:999")],
            expected,
            profile_evidence_complete=True,
        )
    with pytest.raises(ValueError, match="profile evidence contains loss"):
        normalize_h2d_recovery(records, expected, profile_evidence_complete=False)

    wrong_trace_edge = dict(edges[1], trace_id="f" * 32)
    with pytest.raises(ValueError, match="missing or duplicated"):
        normalize_h2d_recovery(
            [wrong_trace_edge if row is edges[1] else row for row in records],
            expected,
            profile_evidence_complete=True,
        )


@pytest.mark.parametrize(
    "record_type",
    ["block_set_chunk", "wait_set_chunk", "transfer_event", "recovery_event"],
)
def test_profile_ledger_accounts_each_capacity_failure_category(record_type) -> None:
    ledger = BoundedKVRecoveryProfileLedger(WORKER_UUID)

    first_seq = ledger.drop(record_type, 10, "serialization_failure")
    second_seq = ledger.drop(record_type, 11, "serialization_failure")
    records, losses = ledger.snapshot()

    assert records == ()
    assert (first_seq, second_seq) == (0, 1)
    assert ledger.attempted_data_count == 2
    assert len(losses) == 1
    assert losses[0].first_record_seq == 0
    assert losses[0].last_record_seq == 1
    assert losses[0].dropped_count == 2
    assert losses[0].counts[record_type] == 2


def test_environment_configuration_requires_recovery_run_id(
    tmp_path: Path,
) -> None:
    config = RuntimeTraceConfig.from_env(
        {
            "VLLM_RLP_TRACE_EXPORT_PATH": str(tmp_path / "trace"),
            "VLLM_RLP_COMMUNICATION_MODE": KV_RECOVERY_COMMUNICATION_MODE,
            "VLLM_RLP_PROFILER_PARENT_COMMIT": "a" * 40,
            "VLLM_RLP_RUNTIME_CORE_COMMIT": "b" * 40,
            "VLLM_RLP_DEVICE_PLUGIN_COMMIT": "c" * 40,
        }
    )

    assert config.communication_mode == KV_RECOVERY_COMMUNICATION_MODE
    assert config.invalid_reason == "schema_incompatible"
    assert not config.enabled


def test_environment_configuration_enables_recovery_mode(tmp_path: Path) -> None:
    config = RuntimeTraceConfig.from_env(
        {
            "VLLM_RLP_TRACE_EXPORT_PATH": str(tmp_path / "trace"),
            "VLLM_RLP_COMMUNICATION_MODE": KV_RECOVERY_COMMUNICATION_MODE,
            "VLLM_RLP_KV_RECOVERY_RUN_ID": RUN_ID,
            "VLLM_RLP_PROFILER_PARENT_COMMIT": "a" * 40,
            "VLLM_RLP_RUNTIME_CORE_COMMIT": "b" * 40,
            "VLLM_RLP_DEVICE_PLUGIN_COMMIT": "c" * 40,
        }
    )

    assert config.enabled
    assert config.invalid_reason is None
    assert config.kv_recovery_profile_config == KVRecoveryProfileConfig(run_id=RUN_ID)


def test_factory_is_none_for_none_mode_and_enabled_for_recovery_mode(
    tmp_path: Path,
) -> None:
    none_sink = JsonlTraceSink(
        tmp_path / "none",
        PROVENANCE,
        clock_ns=lambda: 1000,
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: WORKER_UUID,
    )
    none_hooks = RuntimeLifecycleHooks(
        RuntimeTraceConfig(
            export_path=tmp_path / "none",
            provenance=PROVENANCE,
            communication_mode="none",
        ),
        sink=none_sink,
    )
    none_factory = KVRecoveryObserverFactoryAdapter(
        RUN_ID, none_hooks, FakeBridge(), FAKE_ABI
    )
    assert none_factory.create_scheduler_observer() is None
    assert none_factory.create_worker_observer() is None
    none_hooks.close()

    specialty_hooks = make_hooks(tmp_path)
    specialty_factory = KVRecoveryObserverFactoryAdapter(
        RUN_ID,
        specialty_hooks,
        FakeBridge(),
        FAKE_ABI,
        clock_ns=lambda: 125,
    )
    assert isinstance(
        specialty_factory.create_scheduler_observer(),
        KVRecoverySchedulerAdapter,
    )
    assert isinstance(
        specialty_factory.create_worker_observer(),
        FakeBoundedWorkerObserver,
    )
    assert len(specialty_factory.profile_ledgers) == 1
    specialty_hooks.close()


def test_factory_closes_scheduler_and_process_shards_before_engine_failure(
    tmp_path: Path,
) -> None:
    hooks = make_hooks(tmp_path)
    factory = KVRecoveryObserverFactoryAdapter(
        RUN_ID,
        hooks,
        FakeBridge(),
        FAKE_ABI,
        clock_ns=lambda: 125,
    )
    scheduler = factory.create_scheduler_observer()
    assert isinstance(scheduler, KVRecoverySchedulerAdapter)

    factory.close_for_engine_failure()

    assert scheduler._closed
    records = [
        json.loads(line)
        for path in tmp_path.glob("trace*.jsonl")
        for line in path.read_text().splitlines()
    ]
    assert {record["record_type"] for record in records} >= {
        "process_summary",
        "profile_summary",
    }


def test_none_mode_still_rejects_communication_event(tmp_path: Path) -> None:
    sink = JsonlTraceSink(
        tmp_path / "trace",
        PROVENANCE,
        clock_ns=lambda: 1000,
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: WORKER_UUID,
    )
    span_id = sink.new_span_id()
    assert span_id is not None
    result = sink.write_event(
        EventDraft(
            trace_id=TRACE_ID,
            lifecycle_id=f"{TRACE_ID}:e:0",
            parent_lifecycle_id=f"{TRACE_ID}:r",
            scope="engine_sample",
            component="external_evidence",
            event_name="communication_started",
            timestamp_ns=100,
            preemption_epoch=1,
            start_span_id=span_id,
            sample_index=0,
            metadata={
                "operation": "h2d_restore",
                "direction": "h2d",
                "transfer_id": f"{WORKER_UUID}:t:0",
                "block_set_id": "d" * 64,
                "recovery_profile": "rlp.kv-recovery/v1alpha1",
                "communication_mapping": KV_RECOVERY_COMMUNICATION_MODE,
                "rank": 0,
            },
        )
    )
    close_result = sink.close()

    assert result is None
    assert close_result.dropped_data_count == 1
