from __future__ import annotations

import importlib.util
import json
import os
import sys
from itertools import pairwise
from pathlib import Path

import pytest

from vllm_request_lifecycle_profiler.kv_recovery_profile_protocol import (
    KVRecoveryProfileConfig,
)
from vllm_request_lifecycle_profiler.kv_recovery_runtime import (
    BaseEventRef,
    ExpectedH2DRecovery,
    ExpectedKVRecoveryEpisode,
    KVRecoveryObserverFactoryAdapter,
    KVRecoveryRuntimeABI,
    RequestLifecycleIdentity,
    RuntimeBaseLifecycleBridge,
    normalize_h2d_recovery,
    normalize_kv_recovery_episode,
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
REQUEST_ID = "request-0"
PREEMPTED_ID = f"{ENGINE_UUID}:e:0"
ADMISSION_STARTED_ID = f"{ENGINE_UUID}:e:1"
RESUMED_ID = f"{ENGINE_UUID}:e:2"


class IntegrationBridge:
    def request_identity(
        self, runtime_request_id: str
    ) -> RequestLifecycleIdentity | None:
        if runtime_request_id != REQUEST_ID:
            return None
        return RequestLifecycleIdentity(
            TRACE_ID,
            f"{TRACE_ID}:e:0",
            runtime_request_id,
        )

    def preempted_event(
        self, runtime_request_id: str, recovery_epoch: int
    ) -> BaseEventRef | None:
        if runtime_request_id == REQUEST_ID and recovery_epoch == 1:
            return BaseEventRef(PREEMPTED_ID, 90)
        return None

    def admission_started_event(
        self, runtime_request_id: str, recovery_epoch: int
    ) -> BaseEventRef | None:
        if runtime_request_id == REQUEST_ID and recovery_epoch == 1:
            return BaseEventRef(ADMISSION_STARTED_ID, 130)
        return None

    def resumed_event(
        self, runtime_request_id: str, recovery_epoch: int
    ) -> BaseEventRef | None:
        if runtime_request_id == REQUEST_ID and recovery_epoch == 1:
            return BaseEventRef(RESUMED_ID, 140)
        return None


def load_runtime_abi():
    runtime_source = os.environ.get("VLLM_HUST_G1_SRC", "").strip()
    if not runtime_source:
        pytest.skip("set VLLM_HUST_G1_SRC for the cross-repository CPU gate")
    source_path = Path(runtime_source).resolve()
    if not (source_path / "vllm" / "v1" / "kv_recovery_profile.py").is_file():
        pytest.fail("VLLM_HUST_G1_SRC does not contain the G1 runtime source")
    module_path = source_path / "vllm" / "v1" / "kv_recovery_profile.py"
    module_name = "_vllm_hust_g1_kv_recovery_profile"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        pytest.fail("could not create the exact-runtime ABI module spec")
    runtime = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = runtime
    spec.loader.exec_module(runtime)
    abi = KVRecoveryRuntimeABI(
        binding=runtime.KV_RECOVERY_PROFILE_BINDING,
        identity_type=runtime.KVRecoveryIdentity,
        logical_block_type=runtime.KVRecoveryLogicalBlock,
        transfer_context_type=runtime.KVRecoveryTransferContext,
        compute_context_type=runtime.KVRecoveryComputeContext,
        receipt_type=runtime.KVRecoveryH2DReceipt,
        bounded_worker_observer_type=runtime.BoundedKVRecoveryWorkerObserver,
        canonical_block_set_id=runtime.canonical_block_set_id,
    )
    return abi, runtime


def test_actual_runtime_abi_completes_profiler_whole_trace(tmp_path: Path) -> None:
    abi, runtime = load_runtime_abi()

    sink = JsonlTraceSink(
        tmp_path / "trace",
        RuntimeProvenance("a" * 40, "b" * 40, "c" * 40),
        communication_mode=KV_RECOVERY_COMMUNICATION_MODE,
        kv_recovery_profile_config=KVRecoveryProfileConfig(run_id=RUN_ID),
        clock_ns=lambda: 1000,
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: WORKER_UUID,
    )
    hooks = RuntimeLifecycleHooks(
        RuntimeTraceConfig(
            export_path=tmp_path / "trace",
            provenance=RuntimeProvenance("a" * 40, "b" * 40, "c" * 40),
            communication_mode=KV_RECOVERY_COMMUNICATION_MODE,
            invalid_reason="unsupported_mode",
            kv_recovery_profile_config=KVRecoveryProfileConfig(run_id=RUN_ID),
        ),
        sink=sink,
    )
    bridge = RuntimeBaseLifecycleBridge(hooks)
    identity = RequestLifecycleIdentity(
        TRACE_ID,
        f"{TRACE_ID}:e:0",
        REQUEST_ID,
    )
    assert bridge.register_request(identity)
    active_span_id = hooks.new_span_id()
    assert active_span_id is not None
    active_start = hooks.emit_event(
        EventDraft(
            trace_id=TRACE_ID,
            lifecycle_id=f"{TRACE_ID}:e:0",
            parent_lifecycle_id=f"{TRACE_ID}:r",
            scope="engine_sample",
            component="engine_core",
            event_name="prefill_started",
            timestamp_ns=80,
            preemption_epoch=0,
            start_span_id=active_span_id,
            sample_index=0,
        )
    )
    assert active_start is not None
    preempted = bridge.emit_preempted_and_requeued(
        REQUEST_ID,
        1,
        timestamp_ns=90,
        active_span_start_event_id=active_start.record_id,
        active_span_id=active_span_id,
        prompt_tokens_computed=1,
        prefill_chunk_count=1,
    )
    assert preempted is not None
    factory = KVRecoveryObserverFactoryAdapter(
        RUN_ID,
        hooks,
        bridge,
        abi,
        clock_ns=lambda: 125,
    )
    scheduler = factory.create_scheduler_observer(abi.binding)
    worker = factory.create_worker_observer(abi.binding)
    assert scheduler is not None
    assert worker is not None

    scheduler.request_preempted(REQUEST_ID, 1)
    context = scheduler.prepare_transfer_context(
        REQUEST_ID,
        "h2d_restore",
        (
            runtime.KVRecoveryBlockCoordinate(0, 0),
            runtime.KVRecoveryBlockCoordinate(0, 1),
        ),
    )
    assert context is not None
    attempt = worker.begin_transfer(7, context)
    assert attempt is not None
    worker.transfer_submitted(attempt, 100)
    receipt = worker.transfer_completed(7, 120, True, 256, 10)
    assert receipt is not None
    scheduler.consume_h2d_receipts((receipt,), False)
    admission_started = bridge.emit_admission_started(REQUEST_ID, 1, timestamp_ns=130)
    assert admission_started is not None
    scheduler.request_admission_started(REQUEST_ID, 1)
    scheduler.request_requeued(REQUEST_ID, 1, "token_budget")
    resumed = bridge.emit_resumed(
        REQUEST_ID,
        1,
        timestamp_ns=140,
        prompt_tokens_total=2,
        prompt_tokens_cached=0,
        prompt_tokens_to_compute=2,
    )
    assert resumed is not None
    compute_context = scheduler.request_admitted(REQUEST_ID, 1, "prefill")
    assert isinstance(compute_context, runtime.KVRecoveryComputeContext)
    assert compute_context.compute_kind == "prefill"
    worker.first_compute(compute_context, 150)
    worker.close()
    scheduler.close()

    close_result = hooks.close()
    assert close_result is not None
    assert close_result.close_outcome == "drained"
    assert close_result.profile_summary_written
    shard_path = hooks.committed_shard_path
    profile_path = hooks.committed_kv_recovery_profile_shard_path
    assert shard_path is not None
    assert profile_path is not None
    records = [json.loads(line) for line in shard_path.read_text().splitlines()]
    profile_records = [
        json.loads(line) for line in profile_path.read_text().splitlines()
    ]
    assert [row["record_type"] for row in profile_records] == [
        "profile_start",
        "recovery_event",
        "block_set_chunk",
        "transfer_event",
        "recovery_event",
        "transfer_event",
        "recovery_event",
        "recovery_event",
        "recovery_event",
        "recovery_event",
        "recovery_event",
        "profile_summary",
    ]
    milestones = [
        row for row in profile_records if row["record_type"] == "recovery_event"
    ]
    assert [row["stage"] for row in milestones] == [
        "preempt",
        "restore_start",
        "restore_done",
        "scheduler_wakeup",
        "requeue",
        "admission",
        "first_prefill_or_decode",
    ]
    for predecessor, milestone in pairwise(milestones):
        assert milestone["from_profile_event_id"] == predecessor["record_id"]
    profile_summary = profile_records[-1]
    assert profile_summary["attempted_data_count"] == 10
    assert profile_summary["written_block_set_chunk_count"] == 1
    assert profile_summary["written_transfer_event_count"] == 2
    assert profile_summary["written_recovery_event_count"] == 7
    assert profile_summary["dropped_data_count"] == 0
    profile_complete = all(
        ledger.evidence_complete for ledger in factory.profile_ledgers
    )

    h2d_expected = ExpectedH2DRecovery(
        trace_id=TRACE_ID,
        engine_lifecycle_id=f"{TRACE_ID}:e:0",
        recovery_epoch=1,
        transfer_id=receipt.transfer_id,
        block_set_id=receipt.block_set_id,
        preempted_event_id=preempted.event_id,
        admission_started_event_id=admission_started.event_id,
    )
    normalized = normalize_h2d_recovery(
        records,
        h2d_expected,
        profile_evidence_complete=profile_complete,
    )
    episode = normalize_kv_recovery_episode(
        records,
        profile_records,
        ExpectedKVRecoveryEpisode(
            h2d=h2d_expected,
            run_id=RUN_ID,
            runtime_request_id=REQUEST_ID,
            resumed_event_id=resumed.event_id,
            first_compute_base_event_id=(compute_context.base_phase_start_event_id),
            compute_kind="prefill",
            requeue_reasons=("token_budget",),
            process_uuids=(WORKER_UUID,),
        ),
        profile_evidence_complete=profile_complete,
    )

    assert normalized.duration_ns == 20
    assert normalized.bytes_moved == 256
    assert len(normalized.edge_ids) == 3
    assert episode.h2d == normalized
    assert episode.requeue_count == 1
    assert len(episode.profile_event_ids) == 7

    broken_profile = [dict(row) for row in profile_records]
    admission_row = next(
        row for row in broken_profile if row.get("stage") == "admission"
    )
    admission_row["from_profile_event_id"] = milestones[3]["record_id"]
    with pytest.raises(ValueError, match="predecessor chain"):
        normalize_kv_recovery_episode(
            records,
            broken_profile,
            ExpectedKVRecoveryEpisode(
                h2d=h2d_expected,
                run_id=RUN_ID,
                runtime_request_id=REQUEST_ID,
                resumed_event_id=resumed.event_id,
                first_compute_base_event_id=(compute_context.base_phase_start_event_id),
                compute_kind="prefill",
                requeue_reasons=("token_budget",),
                process_uuids=(WORKER_UUID,),
            ),
            profile_evidence_complete=True,
        )


@pytest.mark.parametrize(
    ("constant_name", "operation"),
    [
        ("MAX_PREPARED_TRANSFER_ATTEMPTS_PER_PROCESS", "prepared"),
        ("MAX_PENDING_H2D_CONTEXTS_PER_PROCESS", "h2d_restore"),
        ("MAX_PENDING_D2H_CONTEXTS_PER_PROCESS", "d2h_preserve"),
    ],
)
def test_actual_runtime_capacity_paths_consume_exact_profile_loss(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    constant_name: str,
    operation: str,
) -> None:
    abi, runtime = load_runtime_abi()
    monkeypatch.setattr(runtime, constant_name, 1)
    sink = JsonlTraceSink(
        tmp_path / "trace",
        RuntimeProvenance("a" * 40, "b" * 40, "c" * 40),
        communication_mode=KV_RECOVERY_COMMUNICATION_MODE,
        kv_recovery_profile_config=KVRecoveryProfileConfig(run_id=RUN_ID),
        clock_ns=lambda: 1000,
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: WORKER_UUID,
    )
    hooks = RuntimeLifecycleHooks(
        RuntimeTraceConfig(
            export_path=tmp_path / "trace",
            provenance=RuntimeProvenance("a" * 40, "b" * 40, "c" * 40),
            communication_mode=KV_RECOVERY_COMMUNICATION_MODE,
            invalid_reason="unsupported_mode",
            kv_recovery_profile_config=KVRecoveryProfileConfig(run_id=RUN_ID),
        ),
        sink=sink,
    )
    factory = KVRecoveryObserverFactoryAdapter(
        RUN_ID,
        hooks,
        IntegrationBridge(),
        abi,
        clock_ns=lambda: 125,
    )
    scheduler = factory.create_scheduler_observer(abi.binding)
    worker = factory.create_worker_observer(abi.binding)
    assert scheduler is not None and worker is not None
    if operation == "h2d_restore":
        scheduler.request_preempted(REQUEST_ID, 1)
    runtime_operation = "d2h_preserve" if operation == "prepared" else operation
    context = scheduler.prepare_transfer_context(
        REQUEST_ID,
        runtime_operation,
        (runtime.KVRecoveryBlockCoordinate(0, 0),),
    )
    assert context is not None

    first = worker.begin_transfer(1, context)
    assert first is not None
    if operation != "prepared":
        worker.transfer_submitted(first, 100)
    second = worker.begin_transfer(2, context)
    if operation == "prepared":
        assert second is None
    else:
        assert second is not None
        worker.transfer_submitted(second, 101)

    ledgers = factory.profile_ledgers
    assert len(ledgers) == 1
    _records, losses = ledgers[0].snapshot()
    assert len(losses) == 1
    assert losses[0].reason == "serialization_failure"
    assert losses[0].counts["transfer_event"] == 1
    assert not ledgers[0].evidence_complete
    hooks.close()


def test_actual_runtime_late_receipt_capacity_keeps_two_edge_prefix(
    tmp_path: Path,
) -> None:
    abi, runtime = load_runtime_abi()
    sink = JsonlTraceSink(
        tmp_path / "trace",
        RuntimeProvenance("a" * 40, "b" * 40, "c" * 40),
        communication_mode=KV_RECOVERY_COMMUNICATION_MODE,
        kv_recovery_profile_config=KVRecoveryProfileConfig(run_id=RUN_ID),
        clock_ns=lambda: 1000,
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: WORKER_UUID,
    )
    hooks = RuntimeLifecycleHooks(
        RuntimeTraceConfig(
            export_path=tmp_path / "trace",
            provenance=RuntimeProvenance("a" * 40, "b" * 40, "c" * 40),
            communication_mode=KV_RECOVERY_COMMUNICATION_MODE,
            invalid_reason="unsupported_mode",
            kv_recovery_profile_config=KVRecoveryProfileConfig(run_id=RUN_ID),
        ),
        sink=sink,
    )
    factory = KVRecoveryObserverFactoryAdapter(
        RUN_ID, hooks, IntegrationBridge(), abi, clock_ns=lambda: 125
    )
    scheduler = factory.create_scheduler_observer(abi.binding)
    worker = factory.create_worker_observer(abi.binding)
    assert scheduler is not None and worker is not None
    scheduler.request_preempted(REQUEST_ID, 1)
    context = scheduler.prepare_transfer_context(
        REQUEST_ID, "h2d_restore", (runtime.KVRecoveryBlockCoordinate(0, 0),)
    )
    assert context is not None
    attempt = worker.begin_transfer(1, context)
    assert attempt is not None
    worker.transfer_submitted(attempt, 100)
    receipt = worker.transfer_completed(1, 120, True, 128, None)
    assert receipt is not None

    worker.h2d_receipt_capacity_exhausted(receipt, "serialization_failure")
    close_result = hooks.close()
    assert close_result is not None
    shard_path = hooks.committed_shard_path
    assert shard_path is not None
    records = [json.loads(line) for line in shard_path.read_text().splitlines()]
    communication_events = [
        row
        for row in records
        if row.get("event_name") in {"communication_started", "communication_done"}
    ]
    edges = [row for row in records if row.get("record_type") == "edge"]
    assert len(communication_events) == 2
    assert len(edges) == 2
    assert all(row.get("to_event_id") != ADMISSION_STARTED_ID for row in edges)
    ledgers = factory.profile_ledgers
    assert len(ledgers) == 1
    _profile_records, losses = ledgers[0].snapshot()
    assert len(losses) == 1
    assert losses[0].reason == "serialization_failure"
    assert losses[0].counts["recovery_event"] == 1
