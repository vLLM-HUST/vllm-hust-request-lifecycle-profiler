from __future__ import annotations

import importlib.util
import json
import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

import pytest

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


def test_disk_free_admission_fails_open_before_creating_a_shard(
    tmp_path: Path,
) -> None:
    required = int(SCHEDULER_WIRE_LIMITS["disk_free_required_bytes"])

    exporter = create_scheduler_profile_exporter(
        _config(tmp_path),
        _identity(),
        disk_free_reader=lambda _path: required - 1,
    )

    assert isinstance(exporter, NullSchedulerProfileExporter)
    assert list(tmp_path.iterdir()) == []


def test_cycle_count_limit_permanently_invalidates_formal_evidence(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    exporter = SchedulerProfileExporter(
        _config(tmp_path), _identity(), clock_ns=_Clock(0, 3_200)
    )
    monkeypatch.setitem(SCHEDULER_WIRE_LIMITS, "max_cycles_in_formal_run", 1)
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

    assert exporter.begin_cycle(fields) is not None
    assert exporter.begin_cycle(fields) is None
    result = exporter.close()

    assert result is not None
    assert result.writer_complete is False
    assert result.formal_invalid_reasons == ("max_cycles_in_formal_run",)
    assert result.dropped_control_count == 1
    assert exporter.committed_shard_path is None
    rows = [json.loads(line) for line in exporter.shard_path.read_text().splitlines()]
    assert sum(row["record_type"] == "schedule_cycle" for row in rows) == 1


def test_rolling_cycle_rate_limit_is_enforced_by_wire_timestamp(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    exporter = SchedulerProfileExporter(
        _config(tmp_path), _identity(), clock_ns=_Clock(0, 3_200)
    )
    monkeypatch.setitem(
        SCHEDULER_WIRE_LIMITS, "max_cycle_rate_per_rolling_second", 1
    )
    cycle = next(
        record
        for record in _golden_records()
        if record["record_type"] == "schedule_cycle"
    )
    first = _body(
        cycle,
        "cycle_seq",
        "schedule_cycle_id",
        "logical_batch_id",
    )
    second = dict(first)
    second["cycle_start_monotonic_ns"] = first["cycle_start_monotonic_ns"] + 1
    second["cycle_end_monotonic_ns"] = first["cycle_end_monotonic_ns"] + 1

    assert exporter.begin_cycle(first) is not None
    assert exporter.begin_cycle(second) is None
    result = exporter.close()

    assert result is not None
    assert result.formal_invalid_reasons == (
        "max_cycle_rate_per_rolling_second",
    )
    assert result.writer_complete is False


def test_rolling_cycle_rate_window_excludes_exactly_one_second_old_cycle(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    exporter = SchedulerProfileExporter(
        _config(tmp_path), _identity(), clock_ns=_Clock(0, 0, 1_000_000_000, 3_200)
    )
    monkeypatch.setitem(
        SCHEDULER_WIRE_LIMITS, "max_cycle_rate_per_rolling_second", 1
    )
    cycle = next(
        record
        for record in _golden_records()
        if record["record_type"] == "schedule_cycle"
    )
    first = _body(
        cycle,
        "cycle_seq",
        "schedule_cycle_id",
        "logical_batch_id",
    )
    second = dict(first)
    second["cycle_start_monotonic_ns"] = (
        first["cycle_start_monotonic_ns"] + 1_000_000_000
    )
    second["cycle_end_monotonic_ns"] = (
        first["cycle_end_monotonic_ns"] + 1_000_000_000
    )

    assert exporter.begin_cycle(first) is not None
    assert exporter.begin_cycle(second) is not None
    result = exporter.close()

    assert result is not None
    assert result.formal_invalid_reasons == ()
    assert result.writer_complete is True


def test_formal_duration_limit_stops_materialization(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    exporter = SchedulerProfileExporter(
        _config(tmp_path), _identity(), clock_ns=_Clock(0, 3_200)
    )
    monkeypatch.setitem(SCHEDULER_WIRE_LIMITS, "max_formal_run_duration_s", 1)
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
    fields["cycle_start_monotonic_ns"] = 1_000_000_001
    fields["cycle_end_monotonic_ns"] = 1_000_000_001

    assert exporter.begin_cycle(fields) is None
    result = exporter.close()

    assert result is not None
    assert result.formal_invalid_reasons == ("max_formal_run_duration_s",)
    assert result.writer_complete is False
    rows = [json.loads(line) for line in exporter.shard_path.read_text().splitlines()]
    assert not any(row["record_type"] == "schedule_cycle" for row in rows)


def test_formal_duration_limit_is_enforced_by_exporter_clock_at_close(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    exporter = SchedulerProfileExporter(
        _config(tmp_path),
        _identity(),
        clock_ns=_Clock(0, 1_000_000_001),
    )
    monkeypatch.setitem(SCHEDULER_WIRE_LIMITS, "max_formal_run_duration_s", 1)

    result = exporter.close()

    assert result is not None
    assert result.close_outcome == "drained"
    assert result.formal_invalid_reasons == ("max_formal_run_duration_s",)
    assert result.writer_complete is False
    assert exporter.committed_shard_path is None


def test_clock_bridge_sample_limit_stops_materialization(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    exporter = SchedulerProfileExporter(
        _config(tmp_path), _identity(), clock_ns=_Clock(0, 3_200)
    )
    monkeypatch.setitem(SCHEDULER_WIRE_LIMITS, "clock_bridge_max_records", 1)
    sample = next(
        record
        for record in _golden_records()
        if record["record_type"] == "clock_bridge_sample"
    )
    fields = _body(sample, "sample_sequence", "clock_domain_id")

    assert exporter.write_clock_bridge_sample(fields) is True
    assert exporter.write_clock_bridge_sample(fields) is False
    result = exporter.close()

    assert result is not None
    assert result.formal_invalid_reasons == ("clock_bridge_max_records",)
    assert result.writer_complete is False
    rows = [json.loads(line) for line in exporter.shard_path.read_text().splitlines()]
    assert sum(row["record_type"] == "clock_bridge_sample" for row in rows) == 1


def test_artifact_byte_limit_stops_planning_and_caps_written_bytes(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    exporter = SchedulerProfileExporter(
        _config(tmp_path), _identity(), clock_ns=_Clock(0, 3_200)
    )
    artifact_limit = exporter._artifact_bytes_planned + int(
        SCHEDULER_WIRE_LIMITS["max_record_bytes_including_lf"]
    )
    monkeypatch.setitem(
        SCHEDULER_WIRE_LIMITS, "artifact_bytes_max", artifact_limit
    )
    sample = next(
        record
        for record in _golden_records()
        if record["record_type"] == "clock_bridge_sample"
    )
    fields = _body(sample, "sample_sequence", "clock_domain_id")

    assert exporter.write_clock_bridge_sample(fields) is False
    result = exporter.close()

    assert result is not None
    assert result.formal_invalid_reasons == ("artifact_bytes_max",)
    assert result.writer_complete is False
    assert result.artifact_bytes_written == exporter.shard_path.stat().st_size
    assert result.artifact_bytes_written <= artifact_limit


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
    assert result.writer_complete is True
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
    assert scheduler_result is not None and scheduler_result.writer_complete
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
    sample = next(
        record
        for record in _golden_records()
        if record["record_type"] == "clock_bridge_sample"
    )
    fields = _body(sample, "sample_sequence", "clock_domain_id")

    for _ in range(int(SCHEDULER_WIRE_LIMITS["data_capacity_records"])):
        assert exporter.write_clock_bridge_sample(fields) is True
    assert exporter.write_clock_bridge_sample(fields) is False
    writer_gate.set()
    result = exporter.close()

    assert result is not None
    assert result.close_outcome == "drained"
    assert result.dropped_data_count == 1
    assert result.writer_complete is False
    assert exporter.committed_shard_path is None
    rows = [json.loads(line) for line in exporter.shard_path.read_text().splitlines()]
    loss = next(row for row in rows if row["record_type"] == "loss_interval")
    assert loss["reason"] == "queue_overflow"
    assert loss["first_dropped_record_seq"] == 1_024
    assert loss["last_dropped_record_seq"] == 1_024
    assert loss["clock_bridge_sample_count"] == 1


def test_serialization_failure_is_loss_accounted_and_not_committed(
    tmp_path: Path,
) -> None:
    exporter = SchedulerProfileExporter(
        _config(tmp_path), _identity(), clock_ns=_Clock(0, 3_200)
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
    fields["unsupported_value"] = object()

    reference = exporter.begin_cycle(fields)
    result = exporter.close()

    assert reference is not None
    assert result is not None
    assert result.dropped_data_count == 1
    assert result.writer_complete is False
    assert exporter.committed_shard_path is None
    rows = [json.loads(line) for line in exporter.shard_path.read_text().splitlines()]
    loss = next(row for row in rows if row["record_type"] == "loss_interval")
    assert loss["reason"] == "serialization_failure"
    assert loss["first_dropped_record_seq"] == 0
    assert loss["last_dropped_record_seq"] == 0


def test_loss_interval_total_is_capped_and_permanently_invalidates(
    tmp_path: Path,
) -> None:
    exporter = SchedulerProfileExporter(
        _config(tmp_path), _identity(), clock_ns=_Clock(0, 3_200)
    )
    sample = next(
        record
        for record in _golden_records()
        if record["record_type"] == "clock_bridge_sample"
    )
    valid_fields = _body(sample, "sample_sequence", "clock_domain_id")
    invalid_fields = dict(valid_fields)
    invalid_fields["unsupported_value"] = object()
    limit = int(SCHEDULER_WIRE_LIMITS["max_loss_interval_records_per_shard"])

    for _ in range(limit):
        assert exporter.write_clock_bridge_sample(invalid_fields) is False
        assert exporter.write_clock_bridge_sample(valid_fields) is True
    assert exporter.write_clock_bridge_sample(invalid_fields) is False
    assert exporter.write_clock_bridge_sample(valid_fields) is False
    assert exporter.write_clock_bridge_sample(valid_fields) is False
    result = exporter.close()

    assert result is not None
    assert result.close_outcome == "drained"
    assert result.written_loss_interval_count == limit
    assert result.formal_invalid_reasons == (
        "max_loss_interval_records_per_shard",
    )
    assert result.writer_complete is False
    assert exporter.committed_shard_path is None
    rows = [json.loads(line) for line in exporter.shard_path.read_text().splitlines()]
    losses = [row for row in rows if row["record_type"] == "loss_interval"]
    assert len(losses) == limit
    assert [row["loss_interval_seq"] for row in losses] == list(range(limit))


def test_writer_complete_is_not_route_b_semantic_admission(tmp_path: Path) -> None:
    exporter = SchedulerProfileExporter(
        _config(tmp_path), _identity(), clock_ns=_Clock(0, 3_200)
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

    assert exporter.begin_cycle(fields) is not None
    result = exporter.close()

    assert result is not None and result.writer_complete is True
    assert exporter.committed_shard_path == exporter.shard_path
    with pytest.raises(CONTRACT.ContractError):
        CONTRACT.validate_scheduler_shard(
            exporter.shard_path,
            CONTRACT.load_json(CONTRACT.CONFIG_PATH),
        )


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
    assert result.writer_complete is False
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


def test_initialization_timeout_cleans_up_before_factory_returns(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    original_timeout = SCHEDULER_WIRE_LIMITS["close_timeout_ms"]
    monkeypatch.setitem(SCHEDULER_WIRE_LIMITS, "close_timeout_ms", 10)

    def delayed_disk_check(_path: Path) -> int:
        time.sleep(0.05)
        return 10**15

    first = create_scheduler_profile_exporter(
        _config(tmp_path),
        _identity(),
        disk_free_reader=delayed_disk_check,
    )

    assert isinstance(first, NullSchedulerProfileExporter)
    assert list(tmp_path.iterdir()) == []

    monkeypatch.setitem(
        SCHEDULER_WIRE_LIMITS, "close_timeout_ms", original_timeout
    )
    second = create_scheduler_profile_exporter(_config(tmp_path), _identity())
    assert isinstance(second, SchedulerProfileExporter)
    result = second.close()
    assert result is not None and result.writer_complete is True


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
