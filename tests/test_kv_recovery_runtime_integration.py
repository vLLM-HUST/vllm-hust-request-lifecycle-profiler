from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import pytest

from vllm_request_lifecycle_profiler.kv_recovery_runtime import (
    BaseEventRef,
    ExpectedH2DRecovery,
    KVRecoveryObserverFactoryAdapter,
    KVRecoveryRuntimeABI,
    RequestLifecycleIdentity,
    normalize_h2d_recovery,
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
    sys.path.insert(0, str(source_path))
    return KVRecoveryRuntimeABI.load()


def test_actual_runtime_abi_completes_profiler_whole_trace(tmp_path: Path) -> None:
    abi = load_runtime_abi()
    from vllm.v1.kv_recovery_profile import KVRecoveryBlockCoordinate

    sink = JsonlTraceSink(
        tmp_path / "trace",
        RuntimeProvenance("a" * 40, "b" * 40, "c" * 40),
        communication_mode=KV_RECOVERY_COMMUNICATION_MODE,
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
    assert scheduler is not None
    assert worker is not None

    scheduler.request_preempted(REQUEST_ID, 1)
    context = scheduler.prepare_transfer_context(
        REQUEST_ID,
        "h2d_restore",
        (KVRecoveryBlockCoordinate(0, 0), KVRecoveryBlockCoordinate(0, 1)),
    )
    assert context is not None
    attempt = worker.begin_transfer(7, context)
    assert attempt is not None
    worker.transfer_submitted(attempt, 100)
    receipt = worker.transfer_completed(7, 120, True, 256, 10)
    assert receipt is not None
    scheduler.consume_h2d_receipts((receipt,), False)
    scheduler.request_admission_started(REQUEST_ID, 1)
    scheduler.request_admitted(REQUEST_ID, 1)
    worker.close()
    scheduler.close()

    close_result = hooks.close()
    assert close_result is not None
    assert close_result.close_outcome == "drained"
    shard_path = hooks.committed_shard_path
    assert shard_path is not None
    records = [json.loads(line) for line in shard_path.read_text().splitlines()]
    records.extend(
        [
            {
                "record_type": "event",
                "event_id": PREEMPTED_ID,
                "event_name": "preempted",
                "trace_id": TRACE_ID,
                "lifecycle_id": f"{TRACE_ID}:e:0",
                "preemption_epoch": 0,
                "timestamp_ns": 90,
            },
            {
                "record_type": "event",
                "event_id": ADMISSION_STARTED_ID,
                "event_name": "admission_started",
                "trace_id": TRACE_ID,
                "lifecycle_id": f"{TRACE_ID}:e:0",
                "preemption_epoch": 1,
                "timestamp_ns": 130,
            },
        ]
    )
    profile_complete = all(
        ledger.evidence_complete for ledger in factory.profile_ledgers
    )

    normalized = normalize_h2d_recovery(
        records,
        ExpectedH2DRecovery(
            trace_id=TRACE_ID,
            engine_lifecycle_id=f"{TRACE_ID}:e:0",
            recovery_epoch=1,
            transfer_id=receipt.transfer_id,
            block_set_id=receipt.block_set_id,
            preempted_event_id=PREEMPTED_ID,
            admission_started_event_id=ADMISSION_STARTED_ID,
        ),
        profile_evidence_complete=profile_complete,
    )

    assert normalized.duration_ns == 20
    assert normalized.bytes_moved == 256
    assert len(normalized.edge_ids) == 3


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
    abi = load_runtime_abi()
    runtime = importlib.import_module("vllm.v1.kv_recovery_profile")
    monkeypatch.setattr(runtime, constant_name, 1)
    sink = JsonlTraceSink(
        tmp_path / "trace",
        RuntimeProvenance("a" * 40, "b" * 40, "c" * 40),
        communication_mode=KV_RECOVERY_COMMUNICATION_MODE,
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
    abi = load_runtime_abi()
    runtime = importlib.import_module("vllm.v1.kv_recovery_profile")
    sink = JsonlTraceSink(
        tmp_path / "trace",
        RuntimeProvenance("a" * 40, "b" * 40, "c" * 40),
        communication_mode=KV_RECOVERY_COMMUNICATION_MODE,
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
