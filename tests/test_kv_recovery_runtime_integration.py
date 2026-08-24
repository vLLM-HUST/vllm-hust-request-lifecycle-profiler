from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from itertools import pairwise
from pathlib import Path

import pytest

from vllm_request_lifecycle_profiler.kv_recovery_profile_protocol import (
    KVRecoveryProfileConfig,
    profile_record_line,
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
            kv_recovery_profile_config=KVRecoveryProfileConfig(run_id=RUN_ID),
        ),
        sink=sink,
    )
    bridge = RuntimeBaseLifecycleBridge(hooks)
    clock_values = iter((80, 90, 100, 110, 130, 135, 140, 145))
    factory = KVRecoveryObserverFactoryAdapter(
        RUN_ID,
        hooks,
        bridge,
        abi,
        clock_ns=lambda: next(clock_values),
    )
    scheduler = factory.create_scheduler_observer()
    worker = factory.create_worker_observer()
    assert scheduler is not None
    assert worker is not None

    scheduler.request_started(REQUEST_ID)
    scheduler.request_scheduled(REQUEST_ID, "prefill", 1, 2, 0)
    scheduler.request_preempted(REQUEST_ID, 1)
    preempted = bridge.preempted_event(REQUEST_ID, 1)
    assert preempted is not None
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
    worker.transfer_submitted(attempt, 115)
    receipt = worker.transfer_completed(7, 120, True, 256, 10)
    assert receipt is not None
    scheduler.consume_h2d_receipts((receipt,), False)
    scheduler.request_admission_started(REQUEST_ID, 1)
    admission_started = bridge.admission_started_event(REQUEST_ID, 1)
    assert admission_started is not None
    scheduler.request_requeued(REQUEST_ID, 1, "token_budget")
    compute_context = scheduler.request_admitted(REQUEST_ID, 1, "prefill", 2, 0)
    resumed = bridge.resumed_event(REQUEST_ID, 1)
    assert resumed is not None
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
        trace_id=context.identity.trace_id,
        engine_lifecycle_id=context.identity.engine_lifecycle_id,
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

    assert normalized.duration_ns == 5
    assert normalized.bytes_moved == 256
    assert len(normalized.edge_ids) == 3
    assert episode.h2d == normalized
    assert episode.requeue_count == 1
    assert len(episode.profile_event_ids) == 7

    corrupted_base = [dict(row) for row in records]
    process_start = next(
        row for row in corrupted_base if row.get("record_type") == "process_start"
    )
    process_start["pid"] += 1
    with pytest.raises(ValueError, match="process_summary content digest differs"):
        normalize_kv_recovery_episode(
            corrupted_base,
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
            profile_evidence_complete=True,
        )

    corrupted_profile = [dict(row) for row in profile_records]
    block_row = next(
        row for row in corrupted_profile if row.get("record_type") == "block_set_chunk"
    )
    block_row["timestamp_ns"] += 1
    with pytest.raises(ValueError, match="profile_summary content digest differs"):
        normalize_kv_recovery_episode(
            records,
            corrupted_profile,
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

    broken_profile = [dict(row) for row in profile_records]
    admission_row = next(
        row for row in broken_profile if row.get("stage") == "admission"
    )
    admission_row["from_profile_event_id"] = milestones[3]["record_id"]
    broken_summary = broken_profile[-1]
    broken_summary["content_sha256"] = hashlib.sha256(
        b"".join(profile_record_line(row) for row in broken_profile[:-1])
    ).hexdigest()
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
    scheduler = factory.create_scheduler_observer()
    worker = factory.create_worker_observer()
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


def test_actual_runtime_wait_precedes_explicit_discard_invalidation(
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
    scheduler = factory.create_scheduler_observer()
    worker = factory.create_worker_observer()
    assert scheduler is not None and worker is not None
    context = scheduler.prepare_transfer_context(
        REQUEST_ID,
        "d2h_preserve",
        (runtime.KVRecoveryBlockCoordinate(0, 0),),
    )
    assert context is not None
    attempt = worker.begin_transfer(7, context)
    assert attempt is not None
    worker.transfer_submitted(attempt, 100)
    membership = worker.prepare_wait(frozenset({7}))
    assert membership is not None

    worker.wait_completed(runtime.KVRecoveryWaitAttempt(membership, 110))
    worker.invalidate_transfers({7})

    # The discard handoff invalidates the context but must not disable the
    # observer: the H2D restore that follows a preemption still needs to be
    # captured.
    assert not worker.evidence_disabled
    assert worker.pending_d2h_count == 0
    assert worker.transfer_completed(7, 120, True, 128, 10) is None
    later = worker.begin_transfer(9, context)
    assert later is not None
    ledger = factory.profile_ledgers[0]
    profile_records, losses = ledger.snapshot()
    assert [record.record_type for record in profile_records] == [
        "block_set_chunk",
        "transfer_event",
        "wait_set_chunk",
        "transfer_event",
    ]
    assert profile_records[-1].fields["transfer_phase"] == "done"
    assert profile_records[-1].fields["success"] is False
    assert profile_records[-1].fields["failure_code"] == "cancelled"
    assert losses == ()
    assert ledger.evidence_complete

    worker.close()
    scheduler.close()
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
            kv_recovery_profile_config=KVRecoveryProfileConfig(run_id=RUN_ID),
        ),
        sink=sink,
    )
    factory = KVRecoveryObserverFactoryAdapter(
        RUN_ID, hooks, IntegrationBridge(), abi, clock_ns=lambda: 125
    )
    scheduler = factory.create_scheduler_observer()
    worker = factory.create_worker_observer()
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


def test_actual_runtime_connector_flow_captures_full_h2d_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drive the real OffloadingConnector scheduler/worker through a
    preemption + H2D restore and assert the profiler produces the complete
    seven-stage recovery chain with no evidence loss.

    This is the cross-repository wiring gate: the observer factory from this
    package is registered in the runtime's ``kv_recovery_profile`` module and
    the actual connector flow (store -> preempt -> restore) runs on the CPU
    test harness. The H2D restore that the runtime performs must be observed
    end-to-end (preempt, restore_start, restore_done, scheduler_wakeup,
    requeue, admission, first_prefill_or_decode) and close ``drained``.
    """
    full_runtime_source = os.environ.get("VLLM_HUST_FULL_SRC", "").strip()
    if not full_runtime_source:
        pytest.skip("set VLLM_HUST_FULL_SRC for the full connector CPU gate")
    source_path = str(Path(full_runtime_source).resolve())
    if source_path not in sys.path:
        sys.path.insert(0, source_path)

    abi = KVRecoveryRuntimeABI.load()
    import vllm.v1.kv_recovery_profile as runtime

    sink = JsonlTraceSink(
        tmp_path / "trace",
        RuntimeProvenance("a" * 40, "b" * 40, "c" * 40),
        communication_mode=KV_RECOVERY_COMMUNICATION_MODE,
        kv_recovery_profile_config=KVRecoveryProfileConfig(run_id=RUN_ID),
        clock_ns=lambda: 1000,
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: ENGINE_UUID,
    )
    hooks = RuntimeLifecycleHooks(
        RuntimeTraceConfig(
            export_path=tmp_path / "trace",
            provenance=RuntimeProvenance("a" * 40, "b" * 40, "c" * 40),
            communication_mode=KV_RECOVERY_COMMUNICATION_MODE,
            kv_recovery_profile_config=KVRecoveryProfileConfig(run_id=RUN_ID),
        ),
        sink=sink,
    )
    bridge = RuntimeBaseLifecycleBridge(hooks)
    factory = KVRecoveryObserverFactoryAdapter(
        RUN_ID,
        hooks,
        bridge,
        abi,
    )
    monkeypatch.setattr(runtime, "_observer_factory", factory)
    runtime._observer_factory_ready_pid = runtime._observer_factory_pid

    import vllm.distributed.kv_transfer.kv_connector.v1.offloading_connector as oc
    from tests.v1.kv_connector.unit.offloading_connector.utils import request_runner

    monkeypatch.setattr(oc, "kv_recovery_runtime_scope_enabled", lambda *a, **k: True)

    from tests.v1.kv_connector.unit.offloading_connector.test_kv_recovery_scheduler import (
        generate_store_output,
    )

    block_size = 4
    block_size_factor = 3
    offloaded_block_size = block_size * block_size_factor
    _runner_gen = request_runner.__wrapped__()
    runner = next(_runner_gen)(
        block_size=block_size,
        num_gpu_blocks=100,
        async_scheduling=True,
        block_size_factor=block_size_factor,
    )

    handler = runner.offloading_spec.handler
    original_complete_jobs = handler.complete_jobs

    def complete_jobs_with_measurements(job_ids):
        original_complete_jobs(job_ids)
        for result in handler.completed_transfers:
            if result.transfer_size is None:
                result.transfer_size = 128
                result.transfer_time = 0.25

    handler.complete_jobs = complete_jobs_with_measurements

    # The real model runner calls observe_kv_recovery_first_compute with the
    # scheduled request IDs at the forward entry; mirror that here so the
    # worker can consume the admitted compute context.
    original_start_kv = runner.worker_connector.connector_worker.start_kv_transfers

    def start_kv_with_first_compute(metadata):
        original_start_kv(metadata)
        runner.worker_connector.observe_kv_recovery_first_compute(
            {req.request_id for req in runner.scheduler.running}
        )

    runner.worker_connector.connector_worker.start_kv_transfers = (
        start_kv_with_first_compute
    )

    free_blocks = runner.scheduler.kv_cache_manager.block_pool.free_block_queue
    initial_free_blocks = free_blocks.num_free_blocks
    runner.new_request(token_ids=[0] * offloaded_block_size * 2)
    runner.manager.prepare_store.side_effect = lambda keys, req_context: (
        generate_store_output(keys)
    )
    runner.run(decoded_tokens=[0], complete_transfers=False)

    runner.manager.prepare_store.side_effect = lambda keys, req_context: (
        generate_store_output(keys)
    )
    runner.run(
        decoded_tokens=[0] * (2 * offloaded_block_size - block_size),
        complete_transfers=False,
    )

    free_blocks.num_free_blocks = 0
    runner.run(
        decoded_tokens=[],
        complete_transfers=False,
        expected_flushed=tuple(range(9)),
        expected_stored=tuple(range(9)),
    )

    free_blocks.num_free_blocks = initial_free_blocks
    runner.scheduler.reset_prefix_cache()
    runner.connector_scheduler._maximal_prefix_lookup = lambda key, context: 3
    runner.manager.prepare_store.side_effect = lambda keys, req_context: (
        generate_store_output(keys)
    )
    runner.run(
        decoded_tokens=[0] * block_size,
        expected_loaded=tuple(range(9)),
    )

    close_result = hooks.close()
    assert close_result is not None
    assert close_result.close_outcome == "drained"
    profile_path = hooks.committed_kv_recovery_profile_shard_path
    assert profile_path is not None
    profile_records = [
        json.loads(line) for line in profile_path.read_text().splitlines()
    ]
    milestones = [
        row for row in profile_records if row["record_type"] == "recovery_event"
    ]
    # The runtime emits zero or more requeue records between scheduler_wakeup
    # and admission (the harness admits directly, so none are expected here).
    assert [row["stage"] for row in milestones] == [
        "preempt",
        "restore_start",
        "restore_done",
        "scheduler_wakeup",
        "admission",
        "first_prefill_or_decode",
    ]
    for predecessor, milestone in pairwise(milestones):
        assert milestone["from_profile_event_id"] == predecessor["record_id"]
    h2d_transfers = [
        row
        for row in profile_records
        if row["record_type"] == "transfer_event" and row["operation"] == "h2d_restore"
    ]
    assert [row["transfer_phase"] for row in h2d_transfers] == ["submit", "done"]
    summary = profile_records[-1]
    assert summary["record_type"] == "profile_summary"
    assert summary["dropped_data_count"] == 0
    assert summary["written_loss_interval_count"] == 0
    assert summary["written_recovery_event_count"] == 6
    assert summary["written_transfer_event_count"] == 6
    assert summary["written_block_set_chunk_count"] >= 3


def test_actual_runtime_records_unassociated_h2d_migration_without_episode(
    tmp_path: Path,
) -> None:
    """Block-level tiering H2D for a running request has no preemption
    episode. The profiler must still record the transfer evidence (block set,
    communication span, transfer submit/done) instead of failing closed."""
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
            kv_recovery_profile_config=KVRecoveryProfileConfig(run_id=RUN_ID),
        ),
        sink=sink,
    )
    bridge = RuntimeBaseLifecycleBridge(hooks)
    factory = KVRecoveryObserverFactoryAdapter(
        RUN_ID,
        hooks,
        bridge,
        abi,
        clock_ns=lambda: 1000,
    )
    scheduler = factory.create_scheduler_observer()
    worker = factory.create_worker_observer()
    assert scheduler is not None and worker is not None

    # A running request with no preemption episode.
    scheduler.request_started(REQUEST_ID)
    scheduler.request_scheduled(REQUEST_ID, "prefill", 1, 2, 0)

    context = scheduler.prepare_transfer_context(
        REQUEST_ID,
        "h2d_restore",
        (
            runtime.KVRecoveryBlockCoordinate(0, 0),
            runtime.KVRecoveryBlockCoordinate(0, 1),
        ),
    )
    assert context is not None
    assert context.identity.recovery_epoch is None
    assert context.identity.episode_id is None
    attempt = worker.begin_transfer(7, context)
    assert attempt is not None
    worker.transfer_submitted(attempt, 110)
    assert worker.transfer_completed(7, 120, True, 256, 10) is None
    worker.close()
    scheduler.close()

    close_result = hooks.close()
    assert close_result is not None
    assert close_result.close_outcome == "drained"
    profile_path = hooks.committed_kv_recovery_profile_shard_path
    assert profile_path is not None
    profile_records = [
        json.loads(line) for line in profile_path.read_text().splitlines()
    ]
    transfer_rows = [
        row
        for row in profile_records
        if row["record_type"] == "transfer_event" and row["operation"] == "h2d_restore"
    ]
    assert [row["transfer_phase"] for row in transfer_rows] == ["submit", "done"]
    assert all(row["recovery_epoch"] is None for row in transfer_rows)
    assert all(row["episode_id"] is None for row in transfer_rows)
    recovery_rows = [
        row for row in profile_records if row["record_type"] == "recovery_event"
    ]
    # No preemption episode -> no recovery stages, and no loss interval.
    assert recovery_rows == []
    summary = profile_records[-1]
    assert summary["record_type"] == "profile_summary"
    assert summary["dropped_data_count"] == 0
    assert summary["written_loss_interval_count"] == 0
    assert summary["written_transfer_event_count"] == 2
    assert summary["written_block_set_chunk_count"] == 1


def test_actual_runtime_multiple_requeues_preserve_order_count_and_reasons(
    tmp_path: Path,
) -> None:
    """Multiple post-wakeup requeues must keep bounded occurrence, order, and
    reason vocabulary while the recovery chain still closes drained."""
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
            kv_recovery_profile_config=KVRecoveryProfileConfig(run_id=RUN_ID),
        ),
        sink=sink,
    )
    bridge = RuntimeBaseLifecycleBridge(hooks)
    factory = KVRecoveryObserverFactoryAdapter(
        RUN_ID,
        hooks,
        bridge,
        abi,
        clock_ns=lambda: 1000,
    )
    scheduler = factory.create_scheduler_observer()
    worker = factory.create_worker_observer()
    assert scheduler is not None and worker is not None

    scheduler.request_started(REQUEST_ID)
    scheduler.request_scheduled(REQUEST_ID, "prefill", 1, 2, 0)
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
    worker.transfer_submitted(attempt, 110)
    receipt = worker.transfer_completed(7, 120, True, 256, 10)
    assert receipt is not None
    scheduler.consume_h2d_receipts((receipt,), False)
    scheduler.request_admission_started(REQUEST_ID, 1)
    # Two requeues with distinct bounded reasons, then admission.
    scheduler.request_requeued(REQUEST_ID, 1, "token_budget")
    scheduler.request_requeued(REQUEST_ID, 1, "block_capacity")
    compute_context = scheduler.request_admitted(REQUEST_ID, 1, "prefill", 2, 0)
    assert compute_context is not None
    worker.first_compute(compute_context, 130)
    worker.close()
    scheduler.close()

    close_result = hooks.close()
    assert close_result is not None
    assert close_result.close_outcome == "drained"
    profile_path = hooks.committed_kv_recovery_profile_shard_path
    assert profile_path is not None
    profile_records = [
        json.loads(line) for line in profile_path.read_text().splitlines()
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
        "requeue",
        "admission",
        "first_prefill_or_decode",
    ]
    requeues = [row for row in milestones if row["stage"] == "requeue"]
    assert [row["occurrence"] for row in requeues] == [0, 1]
    assert [row["requeue_reason"] for row in requeues] == [
        "token_budget",
        "block_capacity",
    ]
    for predecessor, milestone in pairwise(milestones):
        assert milestone["from_profile_event_id"] == predecessor["record_id"]
    summary = profile_records[-1]
    assert summary["record_type"] == "profile_summary"
    assert summary["written_recovery_event_count"] == 8
    assert summary["dropped_data_count"] == 0
    assert summary["written_loss_interval_count"] == 0
