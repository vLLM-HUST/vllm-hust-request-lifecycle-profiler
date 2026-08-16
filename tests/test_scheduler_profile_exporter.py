from __future__ import annotations

import importlib.util
import json
import os
import threading
from collections import deque
from pathlib import Path
from typing import Any

from vllm_request_lifecycle_profiler.runtime_hooks import JsonlTraceSink
from vllm_request_lifecycle_profiler.runtime_protocol import (
    EventDraft,
    RuntimeProvenance,
)
from vllm_request_lifecycle_profiler.scheduler_profile import (
    SCHEDULER_WIRE_LIMITS,
    NullSchedulerProfileExporter,
    ProcessLocalExporterIdentity,
    SchedulerExporterConfig,
    SchedulerProfileExporter,
    SchedulerProvenance,
    SchedulerShardScope,
    create_scheduler_profile_exporter,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_SCRIPT = ROOT / "scripts" / "verify_scheduler_profile_contract.py"
SPEC = importlib.util.spec_from_file_location("scheduler_contract", CONTRACT_SCRIPT)
assert SPEC is not None and SPEC.loader is not None
CONTRACT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTRACT)

PROCESS_ID = "1" * 32
CLOCK_DOMAIN_ID = "2" * 32
PARENT_COMMIT = "3" * 40
RUNTIME_COMMIT = "4" * 40
DEVICE_COMMIT = "5" * 40
TRACE_ID = "6" * 32


class _Clock:
    def __init__(self, *values: int) -> None:
        self._values = deque(values)
        self._last = values[-1]

    def __call__(self) -> int:
        if self._values:
            self._last = self._values.popleft()
        return self._last


def _identity() -> ProcessLocalExporterIdentity:
    return ProcessLocalExporterIdentity(PROCESS_ID, CLOCK_DOMAIN_ID, os.getpid())


def _config(tmp_path: Path) -> SchedulerExporterConfig:
    return SchedulerExporterConfig(
        base_path=tmp_path / "profile",
        scope=SchedulerShardScope("R1", "S1", "SH0"),
        provenance=SchedulerProvenance(
            RUNTIME_COMMIT,
            DEVICE_COMMIT,
            PARENT_COMMIT,
        ),
    )


def _golden_records() -> list[dict[str, Any]]:
    return CONTRACT.load_json(
        CONTRACT.FIXTURES / "scheduler-wire-golden.json"
    )["records"]


def _body(record: dict[str, Any], *owned: str) -> dict[str, Any]:
    excluded = {
        "schema_version",
        "record_type",
        "scheduler_shard_id",
        "record_seq",
        *owned,
    }
    return {key: value for key, value in record.items() if key not in excluded}


def _emit_complete_wire(exporter: SchedulerProfileExporter) -> None:
    references: dict[str, object] = {}
    for record in _golden_records():
        record_type = record["record_type"]
        if record_type in {"scheduler_start", "scheduler_summary", "loss_interval"}:
            continue
        if record_type == "schedule_cycle":
            reference = exporter.begin_cycle(
                _body(
                    record,
                    "cycle_seq",
                    "schedule_cycle_id",
                    "logical_batch_id",
                )
            )
            assert reference is not None
            references[record["logical_batch_id"]] = reference
        elif record_type == "logical_batch":
            reference = references[record["logical_batch_id"]]
            assert exporter.write_logical_batch(
                reference,
                _body(
                    record,
                    "batch_seq",
                    "logical_batch_id",
                    "schedule_cycle_id",
                    "execution_step_id",
                ),
            )
        elif record_type == "execution_step_start":
            reference = next(
                item
                for item in references.values()
                if item.execution_step_id == record["execution_step_id"]
            )
            assert exporter.write_execution_step_start(
                reference,
                _body(
                    record,
                    "execution_step_seq",
                    "execution_step_id",
                    "logical_batch_id",
                ),
            )
        elif record_type == "execution_step_end":
            reference = next(
                item
                for item in references.values()
                if item.execution_step_id == record["execution_step_id"]
            )
            assert exporter.write_execution_step_end(
                reference,
                _body(
                    record,
                    "execution_step_seq",
                    "execution_step_id",
                    "logical_batch_id",
                ),
            )
        else:
            assert record_type == "clock_bridge_sample"
            assert exporter.write_clock_bridge_sample(
                _body(record, "sample_sequence", "clock_domain_id")
            )


def _received() -> EventDraft:
    return EventDraft(
        trace_id=TRACE_ID,
        lifecycle_id=f"{TRACE_ID}:r",
        parent_lifecycle_id=None,
        scope="root_request",
        component="frontend",
        event_name="received",
        metadata={
            "entry_mode": "async_llm",
            "input_mode": "text",
            "response_mode": "none",
            "sampling_n": 1,
            "prompt_count": 1,
            "model_mode": "decoder_only",
            "kv_cache_mode": "disabled",
            "frontend_stop_mode": "none",
            "communication_mode": "none",
        },
    )


def test_i1_limits_are_exactly_the_c1_contract() -> None:
    config = CONTRACT.load_json(CONTRACT.CONFIG_PATH)
    assert SCHEDULER_WIRE_LIMITS == config["wire_limits"]


def test_disabled_scheduler_stream_allocates_nothing(tmp_path: Path) -> None:
    exporter = create_scheduler_profile_exporter(
        SchedulerExporterConfig(base_path=None)
    )

    assert isinstance(exporter, NullSchedulerProfileExporter)
    assert exporter.begin_cycle({}) is None
    assert exporter.shard_path is None
    assert exporter.close() is None
    assert list(tmp_path.iterdir()) == []


def test_i1_exporter_emits_a_c1_valid_route_b_shard(tmp_path: Path) -> None:
    exporter = SchedulerProfileExporter(
        _config(tmp_path),
        _identity(),
        clock_ns=_Clock(0, 3_200),
    )
    _emit_complete_wire(exporter)

    result = exporter.close()

    assert result is not None
    assert result.evidence_complete is True
    assert exporter.committed_shard_path == exporter.shard_path
    assert exporter.shard_path.stat().st_mode & 0o777 == 0o600
    report = CONTRACT.validate_scheduler_shard(
        exporter.shard_path,
        CONTRACT.load_json(CONTRACT.CONFIG_PATH),
    )
    assert report["scope"]["process_instance_id"] == PROCESS_ID
    assert report["scope"]["clock_domain_id"] == CLOCK_DOMAIN_ID
    assert report["data_records"] == 9


def test_lifecycle_and_scheduler_share_identity_but_not_writer_state(
    tmp_path: Path,
) -> None:
    identity = _identity()
    lifecycle = JsonlTraceSink(
        tmp_path / "lifecycle",
        RuntimeProvenance(PARENT_COMMIT, RUNTIME_COMMIT, DEVICE_COMMIT),
        clock_ns=lambda: 0,
        clock_domain_reader=lambda: identity.clock_domain_id,
        process_uuid_factory=lambda: identity.process_instance_id,
    )
    scheduler = SchedulerProfileExporter(
        _config(tmp_path), identity, clock_ns=_Clock(0, 3_200)
    )

    lifecycle_ref = lifecycle.write_event(_received())
    _emit_complete_wire(scheduler)
    lifecycle_result = lifecycle.close()
    scheduler_result = scheduler.close()

    assert lifecycle_ref is not None and lifecycle_ref.record_seq == 0
    assert lifecycle_result.close_outcome == "drained"
    assert scheduler_result is not None and scheduler_result.evidence_complete
    lifecycle_rows = [
        json.loads(line) for line in lifecycle.shard_path.read_text().splitlines()
    ]
    scheduler_rows = [
        json.loads(line) for line in scheduler.shard_path.read_text().splitlines()
    ]
    assert lifecycle_rows[0]["process_uuid"] == PROCESS_ID
    assert scheduler_rows[0]["process_instance_id"] == PROCESS_ID
    assert lifecycle_rows[0]["clock_domain_id"] == CLOCK_DOMAIN_ID
    assert scheduler_rows[0]["clock_domain_id"] == CLOCK_DOMAIN_ID
    assert lifecycle_rows[1]["record_seq"] == 0
    assert scheduler_rows[1]["record_seq"] == 0
    assert lifecycle.shard_path != scheduler.shard_path


def test_scheduler_writer_failure_does_not_poison_lifecycle_writer(
    tmp_path: Path,
) -> None:
    identity = _identity()
    lifecycle = JsonlTraceSink(
        tmp_path / "lifecycle-failure-isolation",
        RuntimeProvenance(PARENT_COMMIT, RUNTIME_COMMIT, DEVICE_COMMIT),
        clock_ns=lambda: 0,
        clock_domain_reader=lambda: identity.clock_domain_id,
        process_uuid_factory=lambda: identity.process_instance_id,
    )
    calls = 0

    def fail_after_scheduler_start(fd: int, raw: bytes | memoryview) -> int:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise OSError("injected scheduler writer failure")
        return os.write(fd, raw)

    scheduler = SchedulerProfileExporter(
        _config(tmp_path),
        identity,
        clock_ns=_Clock(0, 3_200),
        write_function=fail_after_scheduler_start,
    )
    assert lifecycle.write_event(_received()) is not None
    _emit_complete_wire(scheduler)

    scheduler_result = scheduler.close()
    lifecycle_result = lifecycle.close()

    assert scheduler_result is not None
    assert scheduler_result.close_outcome == "writer_failure"
    assert scheduler.committed_shard_path is None
    assert lifecycle_result.close_outcome == "drained"
    assert lifecycle.committed_shard_path == lifecycle.shard_path


def test_queue_overflow_is_loss_accounted_and_never_committed(
    tmp_path: Path,
) -> None:
    writer_gate = threading.Event()
    exporter = SchedulerProfileExporter(
        _config(tmp_path),
        _identity(),
        clock_ns=_Clock(0, 3_200),
        writer_start_gate=writer_gate,
    )
    cycle = next(
        record
        for record in _golden_records()
        if record["record_type"] == "schedule_cycle"
    )
    fields = _body(
        cycle,
        "cycle_seq",
        "schedule_cycle_id",
        "logical_batch_id",
    )

    for _ in range(int(SCHEDULER_WIRE_LIMITS["data_capacity_records"]) + 1):
        assert exporter.begin_cycle(fields) is not None
    writer_gate.set()
    result = exporter.close()

    assert result is not None
    assert result.close_outcome == "drained"
    assert result.dropped_data_count == 1
    assert result.evidence_complete is False
    assert exporter.committed_shard_path is None
    rows = [json.loads(line) for line in exporter.shard_path.read_text().splitlines()]
    loss = next(row for row in rows if row["record_type"] == "loss_interval")
    assert loss["reason"] == "queue_overflow"
    assert loss["first_dropped_record_seq"] == 1_024
    assert loss["last_dropped_record_seq"] == 1_024
    assert loss["schedule_cycle_count"] == 1


def test_serialization_failure_is_loss_accounted_and_not_committed(
    tmp_path: Path,
) -> None:
    exporter = SchedulerProfileExporter(_config(tmp_path), _identity())

    reference = exporter.begin_cycle({"unsupported_value": object()})
    result = exporter.close()

    assert reference is not None
    assert result is not None
    assert result.dropped_data_count == 1
    assert result.evidence_complete is False
    assert exporter.committed_shard_path is None
    rows = [json.loads(line) for line in exporter.shard_path.read_text().splitlines()]
    loss = next(row for row in rows if row["record_type"] == "loss_interval")
    assert loss["reason"] == "serialization_failure"
    assert loss["first_dropped_record_seq"] == 0
    assert loss["last_dropped_record_seq"] == 0


def test_close_timeout_is_bounded_and_not_committed(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    writer_gate = threading.Event()
    exporter = SchedulerProfileExporter(
        _config(tmp_path),
        _identity(),
        writer_start_gate=writer_gate,
    )
    monkeypatch.setitem(SCHEDULER_WIRE_LIMITS, "close_timeout_ms", 20)

    result = exporter.close()

    assert result is not None
    assert result.close_outcome == "timeout"
    assert result.summary_written is False
    assert result.evidence_complete is False
    assert exporter.committed_shard_path is None
    writer_gate.set()
    assert exporter._writer_done.wait(1)


def test_timeout_wins_immutably_over_late_summary_publication(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    summary_write_started = threading.Event()
    release_summary_write = threading.Event()

    def block_summary_write(fd: int, raw: bytes | memoryview) -> int:
        if b'"record_type":"scheduler_summary"' in bytes(raw):
            summary_write_started.set()
            release_summary_write.wait()
        return os.write(fd, raw)

    exporter = SchedulerProfileExporter(
        _config(tmp_path),
        _identity(),
        clock_ns=_Clock(0, 3_200),
        write_function=block_summary_write,
    )
    monkeypatch.setitem(SCHEDULER_WIRE_LIMITS, "close_timeout_ms", 20)

    first_result = exporter.close()

    assert first_result is not None
    assert summary_write_started.is_set()
    assert first_result.close_outcome == "timeout"
    release_summary_write.set()
    assert exporter._writer_done.wait(1)
    second_result = exporter.close()
    assert second_result is first_result
    assert second_result.close_outcome == "timeout"
    assert second_result.summary_written is False
    assert exporter.committed_shard_path is None
    assert exporter.shard_path.read_bytes() == b""
    assert exporter.incomplete_shard_path is not None
    assert exporter.incomplete_shard_path.exists()


def test_factory_keeps_initialization_failure_serving_fail_open(
    tmp_path: Path,
) -> None:
    non_directory = tmp_path / "not-a-directory"
    non_directory.write_text("occupied", encoding="utf-8")
    config = SchedulerExporterConfig(
        base_path=non_directory / "profile",
        scope=SchedulerShardScope("R1", "S1", "SH0"),
        provenance=SchedulerProvenance(
            RUNTIME_COMMIT,
            DEVICE_COMMIT,
            PARENT_COMMIT,
        ),
    )

    exporter = create_scheduler_profile_exporter(config, _identity())

    assert isinstance(exporter, NullSchedulerProfileExporter)
    assert exporter.shard_path is None


def test_start_write_failure_removes_reservation_and_incomplete_shard(
    tmp_path: Path,
) -> None:
    def fail_start_write(_fd: int, _raw: bytes | memoryview) -> int:
        raise OSError("injected scheduler start failure")

    exporter = create_scheduler_profile_exporter(
        _config(tmp_path),
        _identity(),
        write_function=fail_start_write,
    )

    assert isinstance(exporter, NullSchedulerProfileExporter)
    assert list(tmp_path.iterdir()) == []


def test_existing_formal_shard_is_never_overwritten(tmp_path: Path) -> None:
    formal = tmp_path / "profile.rlp-scheduler.SH0.jsonl"
    formal.write_bytes(b"existing\n")

    exporter = create_scheduler_profile_exporter(_config(tmp_path), _identity())

    assert isinstance(exporter, NullSchedulerProfileExporter)
    assert formal.read_bytes() == b"existing\n"
    assert list(tmp_path.iterdir()) == [formal]
