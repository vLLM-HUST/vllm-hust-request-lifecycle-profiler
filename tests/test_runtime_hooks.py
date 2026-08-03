from __future__ import annotations

import hashlib
import json
import logging
import os
import select
import stat
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import vllm_request_lifecycle_profiler.runtime_hooks as runtime_hooks_module
from vllm_request_lifecycle_profiler.legacy_trace import load_legacy_jsonl
from vllm_request_lifecycle_profiler.runtime_hooks import (
    TRACE_COMMUNICATION_MODE_ENV,
    TRACE_DEVICE_COMMIT_ENV,
    TRACE_EXPORT_ENV,
    TRACE_PARENT_COMMIT_ENV,
    TRACE_RUNTIME_COMMIT_ENV,
    JsonlTraceSink,
    RuntimeLifecycleHooks,
    RuntimeTraceConfig,
)
from vllm_request_lifecycle_profiler.runtime_protocol import (
    CLOSE_TIMEOUT_MS,
    DATA_CAPACITY_RECORDS,
    MAX_QUEUED_BYTES,
    RESERVED_CAPACITY_RECORDS,
    EdgeDraft,
    EventDraft,
    RuntimeProvenance,
)
from vllm_request_lifecycle_profiler.trace import LifecycleStage

PARENT_COMMIT = "84261a2458e1f961b0279b70780ca9497bad3f2e"
RUNTIME_COMMIT = "f229ba7cad21a4dba58681af6738a9fd947388e2"
DEVICE_COMMIT = "cafad89a5e103f31ea517c1edb56130578c3cd56"
PROCESS_UUID = "1" * 32
TRACE_ID = "2" * 32
CLOCK_DOMAIN_ID = "3" * 32
REMOTE_PROCESS_UUID = "4" * 32


def _provenance() -> RuntimeProvenance:
    return RuntimeProvenance(PARENT_COMMIT, RUNTIME_COMMIT, DEVICE_COMMIT)


def _received(metadata: dict[str, object] | None = None) -> EventDraft:
    required: dict[str, object] = {
        "entry_mode": "async_llm",
        "input_mode": "text",
        "response_mode": "none",
        "sampling_n": 1,
        "prompt_count": 1,
        "model_mode": "decoder_only",
        "kv_cache_mode": "disabled",
        "frontend_stop_mode": "none",
        "communication_mode": "none",
    }
    if metadata:
        required.update(metadata)
    return EventDraft(
        trace_id=TRACE_ID,
        lifecycle_id=f"{TRACE_ID}:r",
        parent_lifecycle_id=None,
        scope="root_request",
        component="frontend",
        event_name="received",
        metadata=required,
    )


def _edge(index: int) -> EdgeDraft:
    return EdgeDraft(
        trace_id=TRACE_ID,
        from_event_id=f"{REMOTE_PROCESS_UUID}:e:0",
        to_event_id=f"{REMOTE_PROCESS_UUID}:e:{index + 1}",
        edge_kind="data_dependency",
        evidence_source="engine_output_handoff",
    )


def _read_rows(path: Path) -> tuple[list[bytes], list[dict[str, object]]]:
    lines = path.read_bytes().splitlines(keepends=True)
    return lines, [json.loads(line) for line in lines]


def _artifact_path(sink: JsonlTraceSink) -> Path:
    if sink.incomplete_shard_path is not None and sink.incomplete_shard_path.exists():
        return sink.incomplete_shard_path
    assert sink.shard_path.exists()
    return sink.shard_path


def test_runtime_trace_config_is_disabled_without_export_path() -> None:
    config = RuntimeTraceConfig.from_env({})

    assert config.requested is False
    assert config.enabled is False
    assert config.export_path is None


def test_runtime_trace_config_requires_provenance_and_none_communication(
    tmp_path: Path,
) -> None:
    base_env = {TRACE_EXPORT_ENV: str(tmp_path / "trace")}
    missing = RuntimeTraceConfig.from_env(base_env)
    unsupported = RuntimeTraceConfig.from_env(
        base_env | {TRACE_COMMUNICATION_MODE_ENV: "issue2:v1"}
    )
    enabled = RuntimeTraceConfig.from_env(
        base_env
        | {
            TRACE_PARENT_COMMIT_ENV: PARENT_COMMIT,
            TRACE_RUNTIME_COMMIT_ENV: RUNTIME_COMMIT,
            TRACE_DEVICE_COMMIT_ENV: DEVICE_COMMIT,
        }
    )

    assert missing.requested is True
    assert missing.enabled is False
    assert missing.invalid_reason == "schema_incompatible"
    assert unsupported.enabled is False
    assert unsupported.invalid_reason == "unsupported_mode"
    assert enabled.enabled is True
    assert enabled.provenance == _provenance()


def test_disabled_hooks_do_not_create_identity_clock_or_files(tmp_path: Path) -> None:
    hooks = RuntimeLifecycleHooks.from_env({})

    assert hooks.enabled is False
    assert hooks.new_trace_id() is None
    assert hooks.new_span_id() is None
    assert hooks.emit_event(_received()) is None
    assert hooks.shard_path is None
    assert hooks.close() is None
    assert list(tmp_path.iterdir()) == []


def test_v1_sink_writes_private_process_shard_and_reconciled_summary(
    tmp_path: Path,
) -> None:
    base_path = tmp_path / "runtime-trace"
    sink = JsonlTraceSink(
        base_path,
        _provenance(),
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: PROCESS_UUID,
    )

    reference = sink.write_event(_received())
    result = sink.close()
    repeated_result = sink.close()

    assert reference is not None
    assert reference.record_id == f"{PROCESS_UUID}:e:0"
    assert reference.record_seq == 0
    assert result == repeated_result
    assert result.close_outcome == "drained"
    assert result.summary_written is True
    assert sink.committed_shard_path == sink.shard_path
    assert base_path.exists() is False
    assert sink.shard_path == Path(f"{base_path}.rlp.{PROCESS_UUID}.jsonl")
    assert stat.S_IMODE(sink.shard_path.stat().st_mode) == 0o600

    lines, rows = _read_rows(sink.shard_path)
    assert [row["record_type"] for row in rows] == [
        "process_start",
        "event",
        "process_summary",
    ]
    assert all(line.endswith(b"\n") and len(line) <= 4096 for line in lines)
    assert rows[0]["process_uuid"] == PROCESS_UUID
    assert rows[0]["runtime_core_commit"] == RUNTIME_COMMIT
    assert rows[0]["limits"]["data_capacity_records"] == 4096
    assert rows[1]["clock_domain_id"] == CLOCK_DOMAIN_ID
    assert rows[2]["attempted_data_count"] == 1
    assert rows[2]["written_event_count"] == 1
    assert rows[2]["written_edge_count"] == 0
    assert rows[2]["dropped_data_count"] == 0
    assert rows[2]["first_data_record_seq"] == 0
    assert rows[2]["last_data_record_seq"] == 0
    assert rows[2]["content_sha256"] == hashlib.sha256(b"".join(lines[:-1])).hexdigest()


def test_span_and_edge_ids_are_explicit_and_contiguous(tmp_path: Path) -> None:
    sink = JsonlTraceSink(
        tmp_path / "trace",
        _provenance(),
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: PROCESS_UUID,
    )
    received = sink.write_event(_received())
    span_id = sink.new_span_id()
    assert received is not None
    assert span_id == f"{PROCESS_UUID}:s:0"
    render_started = sink.write_event(
        EventDraft(
            trace_id=TRACE_ID,
            lifecycle_id=f"{TRACE_ID}:r",
            parent_lifecycle_id=None,
            scope="root_request",
            component="frontend",
            event_name="render_started",
            start_span_id=span_id,
        )
    )
    render_done = sink.write_event(
        EventDraft(
            trace_id=TRACE_ID,
            lifecycle_id=f"{TRACE_ID}:r",
            parent_lifecycle_id=None,
            scope="root_request",
            component="frontend",
            event_name="render_done",
            end_span_id=span_id,
        )
    )
    assert render_started is not None
    assert render_done is not None
    edge = sink.write_edge(
        EdgeDraft(
            trace_id=TRACE_ID,
            from_event_id=received.record_id,
            to_event_id=render_started.record_id,
            edge_kind="program_order",
            evidence_source="instrumented_execution_context",
        )
    )
    result = sink.close()

    assert edge is not None
    assert [received.record_seq, render_started.record_seq, render_done.record_seq] == [
        0,
        1,
        2,
    ]
    assert edge.record_id == f"{PROCESS_UUID}:g:3"
    assert result.attempted_data_count == 4


def test_serialization_failure_consumes_sequence_and_writes_loss_interval(
    tmp_path: Path,
) -> None:
    sink = JsonlTraceSink(
        tmp_path / "trace",
        _provenance(),
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: PROCESS_UUID,
    )

    assert sink.write_event(_received({"bad_float": 0.5})) is None
    result = sink.close()
    _, rows = _read_rows(sink.shard_path)

    assert result.summary_written is True
    assert result.attempted_data_count == 1
    assert result.written_event_count == 0
    assert result.dropped_data_count == 1
    loss = next(row for row in rows if row["record_type"] == "loss_interval")
    summary = rows[-1]
    assert loss["reason"] == "serialization_failure"
    assert loss["first_dropped_record_seq"] == 0
    assert loss["last_dropped_record_seq"] == 0
    assert loss["event_count"] == 1
    assert loss["edge_count"] == 0
    assert summary["first_data_record_seq"] == 0
    assert summary["last_data_record_seq"] == 0
    assert sink.diagnostic_counts == {"serialization_failure": 1}


def test_queue_overflow_preserves_reserved_terminal_and_exact_loss(
    tmp_path: Path,
) -> None:
    writer_gate = threading.Event()
    sink = JsonlTraceSink(
        tmp_path / "trace",
        _provenance(),
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: PROCESS_UUID,
        writer_start_gate=writer_gate,
    )
    for index in range(DATA_CAPACITY_RECORDS):
        assert sink.write_edge(_edge(index)) is not None
    assert sink.write_edge(_edge(DATA_CAPACITY_RECORDS)) is None

    terminal = sink.write_event(
        EventDraft(
            trace_id=TRACE_ID,
            lifecycle_id=f"{TRACE_ID}:r",
            parent_lifecycle_id=None,
            scope="root_request",
            component="frontend",
            event_name="error",
        )
    )
    assert terminal is not None
    assert terminal.record_seq == DATA_CAPACITY_RECORDS + 1
    writer_gate.set()
    result = sink.close()
    _, rows = _read_rows(sink.shard_path)

    assert result.close_outcome == "drained"
    assert result.attempted_data_count == DATA_CAPACITY_RECORDS + 2
    assert result.written_edge_count == DATA_CAPACITY_RECORDS
    assert result.written_event_count == 1
    assert result.dropped_data_count == 1
    loss = next(row for row in rows if row["record_type"] == "loss_interval")
    assert loss["reason"] == "queue_overflow"
    assert loss["first_dropped_record_seq"] == DATA_CAPACITY_RECORDS
    assert loss["last_dropped_record_seq"] == DATA_CAPACITY_RECORDS
    assert loss["edge_count"] == 1
    assert rows[-1]["last_data_record_seq"] == DATA_CAPACITY_RECORDS + 1


def test_short_writes_are_completed(tmp_path: Path) -> None:
    def short_write(fd: int, data: bytes | memoryview) -> int:
        return os.write(fd, data[:7])

    sink = JsonlTraceSink(
        tmp_path / "trace",
        _provenance(),
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: PROCESS_UUID,
        write_function=short_write,
    )
    assert sink.write_event(_received()) is not None
    result = sink.close()
    _, rows = _read_rows(sink.shard_path)

    assert result.summary_written is True
    assert [row["record_type"] for row in rows] == [
        "process_start",
        "event",
        "process_summary",
    ]


def test_concurrent_producers_allocate_unique_contiguous_record_ids(
    tmp_path: Path,
) -> None:
    writer_gate = threading.Event()
    sink = JsonlTraceSink(
        tmp_path / "trace",
        _provenance(),
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: PROCESS_UUID,
        writer_start_gate=writer_gate,
    )
    with ThreadPoolExecutor(max_workers=8) as executor:
        references = list(
            executor.map(lambda index: sink.write_edge(_edge(index)), range(400))
        )

    assert all(reference is not None for reference in references)
    record_seqs = sorted(
        reference.record_seq for reference in references if reference is not None
    )
    assert record_seqs == list(range(400))
    writer_gate.set()
    result = sink.close()

    assert result.summary_written is True
    assert result.written_edge_count == 400


def test_writer_thread_owns_every_persistent_write(tmp_path: Path) -> None:
    write_thread_ids: list[int] = []
    written_types: list[str] = []

    def tracked_write(fd: int, data: bytes | memoryview) -> int:
        thread_id = threading.get_ident()
        write_thread_ids.append(thread_id)
        written_types.append(json.loads(bytes(data))["record_type"])
        return os.write(fd, data)

    caller_thread_id = threading.get_ident()
    sink = JsonlTraceSink(
        tmp_path / "trace",
        _provenance(),
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: PROCESS_UUID,
        write_function=tracked_write,
    )
    assert sink.write_event(_received()) is not None

    result = sink.close()

    assert result.summary_written is True
    assert written_types == ["process_start", "event", "process_summary"]
    assert len(set(write_thread_ids)) == 1
    assert write_thread_ids[0] != caller_thread_id
    assert write_thread_ids[0] == sink._writer.ident


def test_concurrent_close_is_idempotent_and_writes_one_summary(
    tmp_path: Path,
) -> None:
    sink = JsonlTraceSink(
        tmp_path / "trace",
        _provenance(),
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: PROCESS_UUID,
    )
    assert sink.write_event(_received()) is not None
    barrier = threading.Barrier(16)

    def close_together(_: int) -> object:
        barrier.wait()
        return sink.close()

    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(close_together, range(16)))

    assert len({id(result) for result in results}) == 1
    assert all(result == results[0] for result in results)
    _, rows = _read_rows(sink.shard_path)
    assert sum(row["record_type"] == "process_summary" for row in rows) == 1


def test_close_timeout_is_exact_bounded_and_fails_evidence_closed(
    tmp_path: Path,
) -> None:
    writer_gate = threading.Event()
    sink = JsonlTraceSink(
        tmp_path / "trace",
        _provenance(),
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: PROCESS_UUID,
        writer_start_gate=writer_gate,
    )
    assert sink.write_event(_received()) is not None

    started = time.monotonic()
    result = sink.close()
    elapsed = time.monotonic() - started

    assert elapsed >= CLOSE_TIMEOUT_MS / 1000.0 * 0.9
    assert elapsed < CLOSE_TIMEOUT_MS / 1000.0 + 0.75
    assert result.close_outcome == "timeout"
    assert result.summary_written is False
    assert sink.committed_shard_path is None
    assert result.dropped_data_count == 1
    assert sink.diagnostic_counts == {"close_timeout": 1}
    artifact_path = _artifact_path(sink)
    _, rows = _read_rows(artifact_path)
    assert [row["record_type"] for row in rows] == ["process_start"]
    bytes_at_return = artifact_path.read_bytes()

    writer_gate.set()
    sink._writer.join(timeout=1.0)
    assert sink._writer.is_alive() is False
    assert artifact_path.read_bytes() == bytes_at_return


@pytest.mark.parametrize("lock_name", ["_close_lock", "_condition"])
def test_close_deadline_bounds_every_exporter_lock_acquisition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    lock_name: str,
) -> None:
    sink = JsonlTraceSink(
        tmp_path / "trace",
        _provenance(),
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: PROCESS_UUID,
    )
    monkeypatch.setattr(runtime_hooks_module, "CLOSE_TIMEOUT_MS", 100)
    held = threading.Event()
    release = threading.Event()
    lock = getattr(sink, lock_name)

    def hold_lock() -> None:
        lock.acquire()
        held.set()
        release.wait(timeout=2.0)
        lock.release()

    holder = threading.Thread(target=hold_lock)
    holder.start()
    assert held.wait(timeout=1.0)
    try:
        started = time.monotonic()
        result = sink.close()
        elapsed = time.monotonic() - started

        assert elapsed >= 0.075
        assert elapsed < 0.35
        assert result.close_outcome == "timeout"
        assert result.summary_written is False
        repeated_started = time.monotonic()
        repeated_result = sink.close()
        assert time.monotonic() - repeated_started < 0.05
        assert repeated_result is result
        assert sink._atexit_registered is False
    finally:
        release.set()
        holder.join(timeout=1.0)
        sink._writer.join(timeout=1.0)
        sink._unregister_atexit()

    assert holder.is_alive() is False
    assert sink._writer.is_alive() is False
    assert sink._fd == -1
    _, rows = _read_rows(_artifact_path(sink))
    assert [row["record_type"] for row in rows] == ["process_start"]


def test_public_close_never_runs_timeout_filesystem_or_logging_handlers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer_gate = threading.Event()
    handler_entered = threading.Event()
    release_handler = threading.Event()
    caller_thread_id = threading.get_ident()
    namespace_thread_ids: list[int] = []

    class BlockingHandler(logging.Handler):
        def emit(self, _record: logging.LogRecord) -> None:
            handler_entered.set()
            release_handler.wait(timeout=10.0)

    sink = JsonlTraceSink(
        tmp_path / "trace",
        _provenance(),
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: PROCESS_UUID,
        writer_start_gate=writer_gate,
    )
    hooks = RuntimeLifecycleHooks(
        RuntimeTraceConfig(export_path=tmp_path / "trace", provenance=_provenance()),
        sink=sink,
    )
    assert hooks.emit_event(_received()) is not None
    module_logger = logging.getLogger(runtime_hooks_module.__name__)
    old_level = module_logger.level
    handler = BlockingHandler(level=logging.WARNING)
    module_logger.setLevel(logging.WARNING)
    module_logger.addHandler(handler)
    original_link = os.link
    original_replace = os.replace
    original_unlink = Path.unlink

    def track_link(*args: object, **kwargs: object) -> None:
        namespace_thread_ids.append(threading.get_ident())
        original_link(*args, **kwargs)

    def track_replace(*args: object, **kwargs: object) -> None:
        namespace_thread_ids.append(threading.get_ident())
        original_replace(*args, **kwargs)

    def track_unlink(self: Path, *args: object, **kwargs: object) -> None:
        namespace_thread_ids.append(threading.get_ident())
        original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(runtime_hooks_module.os, "link", track_link)
    monkeypatch.setattr(runtime_hooks_module.os, "replace", track_replace)
    monkeypatch.setattr(Path, "unlink", track_unlink)

    try:
        started = time.monotonic()
        result = hooks.close()
        elapsed = time.monotonic() - started

        assert result is not None
        assert result.close_outcome == "timeout"
        assert elapsed < CLOSE_TIMEOUT_MS / 1000.0 + 0.2
        assert caller_thread_id not in namespace_thread_ids
        assert handler_entered.wait(timeout=1.0)
    finally:
        release_handler.set()
        writer_gate.set()
        sink._writer.join(timeout=1.0)
        module_logger.removeHandler(handler)
        module_logger.setLevel(old_level)


def test_gate_release_at_1970ms_is_not_classified_as_close_timeout(
    tmp_path: Path,
) -> None:
    writer_gate = threading.Event()
    sink = JsonlTraceSink(
        tmp_path / "trace",
        _provenance(),
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: PROCESS_UUID,
        writer_start_gate=writer_gate,
    )
    assert sink.write_event(_received()) is not None
    release = threading.Timer(1.97, writer_gate.set)
    release.start()

    result = sink.close()
    release.join()
    _, rows = _read_rows(_artifact_path(sink))

    assert result.written_event_count == 1
    assert result.dropped_data_count == 0
    assert any(row["record_type"] == "event" for row in rows)
    assert not any(
        row["record_type"] == "loss_interval" and row["reason"] == "close_timeout"
        for row in rows
    )


def test_final_publication_crossing_deadline_is_retracted_asynchronously(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    final_publish_entered = threading.Event()
    release_final_publish = threading.Event()
    original_replace = os.replace
    sink = JsonlTraceSink(
        tmp_path / "trace",
        _provenance(),
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: PROCESS_UUID,
    )

    def block_final_publication(source: Path, target: Path) -> None:
        if (
            sink.incomplete_shard_path is not None
            and Path(source) == sink.incomplete_shard_path
            and Path(target) == sink.shard_path
        ):
            final_publish_entered.set()
            release_final_publish.wait(timeout=10.0)
        original_replace(source, target)

    monkeypatch.setattr(runtime_hooks_module.os, "replace", block_final_publication)
    assert sink.write_event(_received()) is not None

    result_holder: list[object] = []
    closer = threading.Thread(target=lambda: result_holder.append(sink.close()))
    closer.start()
    assert final_publish_entered.wait(timeout=1.0)
    closer.join(timeout=CLOSE_TIMEOUT_MS / 1000.0 + 0.2)

    assert closer.is_alive() is False
    result = result_holder[0]
    assert result.close_outcome == "timeout"
    assert result.summary_written is False
    assert sink.shard_path.read_bytes() == b""
    assert sink.incomplete_shard_path is not None
    assert sink.incomplete_shard_path.exists()

    release_final_publish.set()
    sink._writer.join(timeout=1.0)
    assert sink._writer.is_alive() is False
    assert sink.shard_path.exists() is False
    assert sink.incomplete_shard_path is not None
    assert sink.incomplete_shard_path.exists()


@pytest.mark.parametrize("invalidation_fails", [False, True])
def test_late_publication_rollback_failures_are_receipt_gated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalidation_fails: bool,
) -> None:
    sink = JsonlTraceSink(
        tmp_path / "trace",
        _provenance(),
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: PROCESS_UUID,
    )
    monkeypatch.setattr(runtime_hooks_module, "CLOSE_TIMEOUT_MS", 100)
    final_publish_entered = threading.Event()
    release_final_publish = threading.Event()
    invalidation_reservations: list[tuple[int, int, int]] = []
    original_replace = os.replace
    original_unlink = Path.unlink
    original_open = os.open
    original_write = os.write

    def controlled_replace(source: Path, target: Path) -> None:
        source_path = Path(source)
        target_path = Path(target)
        if (
            sink.incomplete_shard_path is not None
            and source_path == sink.incomplete_shard_path
            and target_path == sink.shard_path
        ):
            final_publish_entered.set()
            release_final_publish.wait(timeout=2.0)
            original_replace(source, target)
            return
        if (
            source_path == sink.shard_path
            and sink.incomplete_shard_path is not None
            and target_path == sink.incomplete_shard_path
        ):
            raise OSError("injected late-publication retraction failure")
        original_replace(source, target)

    def controlled_unlink(self: Path, missing_ok: bool = False) -> None:
        if self == sink.shard_path:
            raise OSError("injected late-publication unlink failure")
        original_unlink(self, missing_ok=missing_ok)

    def controlled_open(path: Path, flags: int, mode: int = 0o777) -> int:
        if invalidation_fails and Path(path) == sink.shard_path and flags & os.O_APPEND:
            assert sink._reserved_queued == 1
            assert sink._queued_bytes > 0
            raise OSError("injected invalidation append failure")
        return original_open(path, flags, mode)

    def observe_write(fd: int, data: bytes | memoryview) -> int:
        raw = bytes(data)
        try:
            row = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            row = {}
        if (
            row.get("record_type") == "process_summary"
            and row.get("close_outcome") == "timeout"
        ):
            invalidation_reservations.append(
                (sink._reserved_queued, sink._queued_bytes, len(raw))
            )
        return original_write(fd, data)

    monkeypatch.setattr(runtime_hooks_module.os, "replace", controlled_replace)
    monkeypatch.setattr(Path, "unlink", controlled_unlink)
    monkeypatch.setattr(runtime_hooks_module.os, "open", controlled_open)
    monkeypatch.setattr(runtime_hooks_module.os, "write", observe_write)
    assert sink.write_event(_received()) is not None
    result_holder: list[object] = []
    closer = threading.Thread(target=lambda: result_holder.append(sink.close()))
    closer.start()
    try:
        assert final_publish_entered.wait(timeout=1.0)
        closer.join(timeout=0.35)
        assert closer.is_alive() is False
        result = result_holder[0]
        assert result.close_outcome == "timeout"
        assert result.summary_written is False
        assert sink.committed_shard_path is None
        assert sink.shard_path.read_bytes() == b""
    finally:
        release_final_publish.set()
        closer.join(timeout=1.0)
        sink._writer.join(timeout=1.0)

    assert sink._writer.is_alive() is False
    _, rows = _read_rows(sink.shard_path)
    summaries = [row for row in rows if row["record_type"] == "process_summary"]
    if invalidation_fails:
        # Namespace retraction, unlink, and append can all fail after a
        # successful syscall. Such bytes are never admitted because the
        # immutable timeout receipt cannot produce a committed manifest path.
        assert [row["close_outcome"] for row in summaries] == ["drained"]
        assert invalidation_reservations == []
        assert sink._dropped_control_count >= 1
    else:
        assert [row["close_outcome"] for row in summaries] == [
            "drained",
            "timeout",
        ]
        assert len(invalidation_reservations) == 1
        reserved_records, reserved_bytes, raw_size = invalidation_reservations[0]
        assert reserved_records == 1
        assert reserved_bytes >= raw_size
    assert sink._reserved_queued == 0
    assert sink._queued_bytes == 0
    assert sink.committed_shard_path is None


def test_publication_commits_drained_result_before_writer_thread_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = JsonlTraceSink(
        tmp_path / "trace",
        _provenance(),
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: PROCESS_UUID,
    )
    monkeypatch.setattr(runtime_hooks_module, "CLOSE_TIMEOUT_MS", 100)
    publication_committed = threading.Event()
    release_writer = threading.Event()
    original_publish = sink._publish_completed_shard_in_writer

    def publish_then_pause() -> bool:
        published = original_publish()
        if published:
            publication_committed.set()
            release_writer.wait(timeout=2.0)
        return published

    monkeypatch.setattr(sink, "_publish_completed_shard_in_writer", publish_then_pause)
    assert sink.write_event(_received()) is not None
    result_holder: list[object] = []
    closer = threading.Thread(target=lambda: result_holder.append(sink.close()))
    closer.start()
    try:
        assert publication_committed.wait(timeout=1.0)
        closer.join(timeout=0.35)
        assert closer.is_alive() is False
        result = result_holder[0]
        assert result.close_outcome == "drained"
        assert result.summary_written is True
        assert sink._close_result is result
        assert sink._closed is True
        _, rows = _read_rows(sink.shard_path)
        assert [row["record_type"] for row in rows] == [
            "process_start",
            "event",
            "process_summary",
        ]
    finally:
        release_writer.set()
        closer.join(timeout=1.0)
        sink._writer.join(timeout=1.0)

    assert sink._writer.is_alive() is False


def test_lock_free_timeout_cannot_overwrite_publication_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = JsonlTraceSink(
        tmp_path / "trace",
        _provenance(),
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: PROCESS_UUID,
    )
    monkeypatch.setattr(runtime_hooks_module, "CLOSE_TIMEOUT_MS", 100)
    writer_before_claim = threading.Event()
    release_writer = threading.Event()
    original_claim = sink._claim_close_result

    def pause_drained_claim(
        close_outcome: str, summary_written: bool
    ) -> tuple[object, bool]:
        if close_outcome == "drained" and summary_written:
            writer_before_claim.set()
            release_writer.wait(timeout=2.0)
        return original_claim(close_outcome, summary_written)

    monkeypatch.setattr(sink, "_claim_close_result", pause_drained_claim)
    assert sink.write_event(_received()) is not None
    result_holder: list[object] = []
    closer = threading.Thread(target=lambda: result_holder.append(sink.close()))
    closer.start()
    try:
        assert writer_before_claim.wait(timeout=1.0)
        closer.join(timeout=0.35)
        assert closer.is_alive() is False
        result = result_holder[0]
        assert result.close_outcome == "timeout"
        assert result.summary_written is False
        assert sink.committed_shard_path is None
    finally:
        release_writer.set()
        closer.join(timeout=1.0)
        sink._writer.join(timeout=1.0)

    assert sink._writer.is_alive() is False
    assert sink.shard_path.exists() is False
    assert sink.incomplete_shard_path is not None
    _, rows = _read_rows(sink.incomplete_shard_path)
    assert rows[-1]["record_type"] == "process_summary"
    assert rows[-1]["close_outcome"] == "drained"
    assert sink.committed_shard_path is None


def test_uuid_reservation_survives_incomplete_publication_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base_path = tmp_path / "trace"
    sink = JsonlTraceSink(
        base_path,
        _provenance(),
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: PROCESS_UUID,
    )
    final_publish_entered = threading.Event()
    release_final_publish = threading.Event()
    original_replace = os.replace

    def block_final_publication(source: Path, target: Path) -> None:
        if (
            sink.incomplete_shard_path is not None
            and Path(source) == sink.incomplete_shard_path
            and Path(target) == sink.shard_path
        ):
            final_publish_entered.set()
            release_final_publish.wait(timeout=2.0)
        original_replace(source, target)

    monkeypatch.setattr(runtime_hooks_module.os, "replace", block_final_publication)
    assert sink.write_event(_received()) is not None
    result_holder: list[object] = []
    closer = threading.Thread(target=lambda: result_holder.append(sink.close()))
    closer.start()
    try:
        assert final_publish_entered.wait(timeout=1.0)
        assert sink.shard_path.read_bytes() == b""
        assert stat.S_IMODE(sink.shard_path.stat().st_mode) == 0o600
        assert sink.incomplete_shard_path is not None
        assert sink.shard_path.stat().st_ino != sink.incomplete_shard_path.stat().st_ino
        with pytest.raises(FileExistsError, match="unique process shard"):
            JsonlTraceSink(
                base_path,
                _provenance(),
                clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
                process_uuid_factory=lambda: PROCESS_UUID,
            )
    finally:
        release_final_publish.set()
        closer.join(timeout=1.0)
        sink._writer.join(timeout=1.0)

    result = result_holder[0]
    assert result.close_outcome == "drained"
    assert result.summary_written is True
    assert sink.committed_shard_path == sink.shard_path
    _, rows = _read_rows(sink.shard_path)
    assert sum(row["record_type"] == "process_summary" for row in rows) == 1


def test_blocked_injected_write_cannot_append_after_close_returns(
    tmp_path: Path,
) -> None:
    event_write_entered = threading.Event()
    release_event_write = threading.Event()

    def block_event_write(fd: int, data: bytes | memoryview) -> int:
        record_type = json.loads(bytes(data))["record_type"]
        if record_type == "event":
            event_write_entered.set()
            release_event_write.wait(timeout=10.0)
        return os.write(fd, data)

    sink = JsonlTraceSink(
        tmp_path / "trace",
        _provenance(),
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: PROCESS_UUID,
        write_function=block_event_write,
    )
    assert sink.write_event(_received()) is not None
    assert event_write_entered.wait(timeout=1.0)

    result = sink.close()
    artifact_path = _artifact_path(sink)
    bytes_at_return = artifact_path.read_bytes()

    assert result.close_outcome == "timeout"
    assert result.summary_written is False
    assert result.dropped_data_count == 1
    release_event_write.set()
    sink._writer.join(timeout=1.0)
    assert sink._writer.is_alive() is False
    assert artifact_path.read_bytes() == bytes_at_return
    assert [row["record_type"] for row in _read_rows(artifact_path)[1]] == [
        "process_start"
    ]


def test_persistent_summary_crossing_deadline_is_quarantined_and_invalidated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary_write_entered = threading.Event()
    release_summary_write = threading.Event()
    original_write = os.write

    def block_persistent_summary(fd: int, data: bytes | memoryview) -> int:
        try:
            record_type = json.loads(bytes(data))["record_type"]
        except (KeyError, TypeError, json.JSONDecodeError):
            record_type = None
        if record_type == "process_summary" and not summary_write_entered.is_set():
            summary_write_entered.set()
            release_summary_write.wait(timeout=10.0)
        return original_write(fd, data)

    monkeypatch.setattr(runtime_hooks_module.os, "write", block_persistent_summary)
    sink = JsonlTraceSink(
        tmp_path / "trace",
        _provenance(),
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: PROCESS_UUID,
    )
    assert sink.write_event(_received()) is not None

    result_holder: list[object] = []

    def close_sink() -> None:
        result_holder.append(sink.close())

    closer = threading.Thread(target=close_sink)
    closer.start()
    assert summary_write_entered.wait(timeout=1.0)
    closer.join(timeout=CLOSE_TIMEOUT_MS / 1000.0 + 1.0)
    assert closer.is_alive() is False
    result = result_holder[0]
    assert result.close_outcome == "timeout"
    assert result.summary_written is False
    assert sink.shard_path.read_bytes() == b""
    assert list(tmp_path.glob("trace.rlp.*.jsonl")) == [sink.shard_path]
    artifact_path = _artifact_path(sink)

    release_summary_write.set()
    sink._writer.join(timeout=1.0)
    assert sink._writer.is_alive() is False
    _, rows = _read_rows(artifact_path)
    summaries = [row for row in rows if row["record_type"] == "process_summary"]
    assert [row["close_outcome"] for row in summaries] == ["drained", "timeout"]
    assert rows[-1]["record_type"] == "process_summary"
    assert rows[-1]["close_outcome"] == "timeout"
    assert sink.shard_path.read_bytes() == b""


def test_clock_failure_after_sequence_allocation_is_accounted_and_logged_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    clock_calls = 0

    def intermittent_clock() -> int:
        nonlocal clock_calls
        clock_calls += 1
        if 2 <= clock_calls <= 4:
            raise OSError("injected clock failure")
        return clock_calls

    sink = JsonlTraceSink(
        tmp_path / "trace",
        _provenance(),
        clock_ns=intermittent_clock,
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: PROCESS_UUID,
    )

    assert [sink.write_event(_received()) for _ in range(3)] == [None, None, None]
    result = sink.close()
    _, rows = _read_rows(sink.shard_path)

    assert result.summary_written is True
    assert result.attempted_data_count == 3
    assert result.dropped_data_count == 3
    assert sink.diagnostic_counts == {
        "clock_domain_unavailable": 3,
        "serialization_failure": 3,
    }
    assert rows[1]["record_type"] == "loss_interval"
    assert rows[1]["first_dropped_record_seq"] == 0
    assert rows[1]["last_dropped_record_seq"] == 2
    messages = [record.getMessage() for record in caplog.records]
    assert sum("clock_domain_unavailable" in message for message in messages) == 1
    assert sum("serialization_failure" in message for message in messages) == 1


def test_producer_never_runs_blocking_diagnostic_handler(tmp_path: Path) -> None:
    handler_entered = threading.Event()
    release_handler = threading.Event()
    handler_finished = threading.Event()
    handler_threads: list[str] = []
    handler_messages: list[str] = []

    class BlockingHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            handler_threads.append(threading.current_thread().name)
            handler_messages.append(record.getMessage())
            handler_entered.set()
            release_handler.wait(timeout=2.0)
            handler_finished.set()

    sink = JsonlTraceSink(
        tmp_path / "trace",
        _provenance(),
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: PROCESS_UUID,
    )
    module_logger = logging.getLogger(runtime_hooks_module.__name__)
    old_level = module_logger.level
    handler = BlockingHandler(level=logging.WARNING)
    module_logger.setLevel(logging.WARNING)
    module_logger.addHandler(handler)
    invalid_event = _received({"sampling_n": 0})
    producer_results: list[object] = []

    try:
        producer = threading.Thread(
            target=lambda: producer_results.append(sink.write_event(invalid_event)),
            name="serving-producer",
        )
        producer.start()
        producer.join(timeout=0.5)

        assert producer.is_alive() is False
        assert producer_results == [None]
        assert handler_entered.wait(timeout=1.0)
        assert handler_threads == [sink._writer.name]

        # A duplicate reason is counted but never schedules another handler call.
        assert sink.write_event(invalid_event) is None
    finally:
        release_handler.set()
        handler_finished.wait(timeout=1.0)
        module_logger.removeHandler(handler)
        module_logger.setLevel(old_level)

    result = sink.close()
    assert result.close_outcome == "drained"
    assert sink.diagnostic_counts == {"serialization_failure": 2}
    assert sum("serialization_failure" in message for message in handler_messages) == 1


def test_reserved_capacity_exhaustion_is_explicitly_invalidated(
    tmp_path: Path,
) -> None:
    writer_gate = threading.Event()
    sink = JsonlTraceSink(
        tmp_path / "trace",
        _provenance(),
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: PROCESS_UUID,
        writer_start_gate=writer_gate,
    )
    terminal = EventDraft(
        trace_id=TRACE_ID,
        lifecycle_id=f"{TRACE_ID}:r",
        parent_lifecycle_id=None,
        scope="root_request",
        component="frontend",
        event_name="error",
    )
    for _ in range(64):
        assert sink.write_event(terminal) is not None
    assert sink.write_event(terminal) is None

    release = threading.Timer(0.05, writer_gate.set)
    release.start()
    result = sink.close()
    release.join()
    _, rows = _read_rows(sink.shard_path)

    assert result.close_outcome == "drained"
    assert result.summary_written is True
    assert result.attempted_data_count == 65
    assert result.written_event_count == 64
    assert result.dropped_data_count == 1
    assert result.dropped_control_count == 1
    assert not any(row["record_type"] == "loss_interval" for row in rows)
    assert rows[-1]["dropped_control_count"] == 1


@pytest.mark.parametrize(
    ("invalidation_method", "capacity_kind"),
    [
        ("persistent", "records"),
        ("persistent", "bytes"),
        ("path", "records"),
        ("path", "bytes"),
    ],
)
def test_every_invalidation_summary_obeys_reserved_capacity(
    tmp_path: Path,
    invalidation_method: str,
    capacity_kind: str,
) -> None:
    writer_gate = threading.Event()
    sink = JsonlTraceSink(
        tmp_path / "trace",
        _provenance(),
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: PROCESS_UUID,
        writer_start_gate=writer_gate,
    )
    bytes_before = sink.shard_path.read_bytes()
    with sink._condition:
        if capacity_kind == "records":
            sink._reserved_queued = RESERVED_CAPACITY_RECORDS
        else:
            sink._queued_bytes = MAX_QUEUED_BYTES
        dropped_before = sink._dropped_control_count

    if invalidation_method == "persistent":
        sink._append_timeout_invalidation_in_writer()
    else:
        sink._append_invalidation_to_path_in_writer(sink.shard_path)

    with sink._condition:
        assert sink._dropped_control_count == dropped_before + 1
        if capacity_kind == "records":
            assert sink._reserved_queued == RESERVED_CAPACITY_RECORDS
            sink._reserved_queued = 0
        else:
            assert sink._queued_bytes == MAX_QUEUED_BYTES
            sink._queued_bytes = 0
        sink._abandoned = True
        sink._condition.notify_all()
    assert sink.shard_path.read_bytes() == bytes_before
    writer_gate.set()
    sink._writer.join(timeout=1.0)
    sink._unregister_atexit()
    assert sink._writer.is_alive() is False


@pytest.mark.parametrize("invalidation_method", ["persistent", "path"])
def test_invalidation_reservation_is_released_after_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalidation_method: str,
) -> None:
    writer_gate = threading.Event()
    sink = JsonlTraceSink(
        tmp_path / "trace",
        _provenance(),
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: PROCESS_UUID,
        writer_start_gate=writer_gate,
    )
    bytes_before = sink.shard_path.read_bytes()
    dropped_before = sink._dropped_control_count

    if invalidation_method == "persistent":

        def fail_persistent_write(_raw: bytes) -> None:
            assert sink._reserved_queued == 1
            assert sink._queued_bytes > 0
            raise OSError("injected invalidation write failure")

        monkeypatch.setattr(sink, "_write_persistent_all", fail_persistent_write)
        sink._append_timeout_invalidation_in_writer()
    else:
        original_open = os.open

        def fail_append_open(path: Path, flags: int, mode: int = 0o777) -> int:
            if Path(path) == sink.shard_path and flags & os.O_APPEND:
                assert sink._reserved_queued == 1
                assert sink._queued_bytes > 0
                raise OSError("injected invalidation open failure")
            return original_open(path, flags, mode)

        monkeypatch.setattr(runtime_hooks_module.os, "open", fail_append_open)
        sink._append_invalidation_to_path_in_writer(sink.shard_path)

    with sink._condition:
        assert sink._dropped_control_count == dropped_before + 1
        assert sink._reserved_queued == 0
        assert sink._queued_bytes == 0
        sink._abandoned = True
        sink._condition.notify_all()
    assert sink.shard_path.read_bytes() == bytes_before
    writer_gate.set()
    sink._writer.join(timeout=1.0)
    sink._unregister_atexit()
    assert sink._writer.is_alive() is False


def test_timeout_finalizer_never_materializes_more_than_64_controls(
    tmp_path: Path,
) -> None:
    writer_gate = threading.Event()
    sink = JsonlTraceSink(
        tmp_path / "trace",
        _provenance(),
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: PROCESS_UUID,
        writer_start_gate=writer_gate,
    )
    for index in range(33):
        assert sink.write_event(_received({"bad_float": 0.5})) is None
        assert sink.write_edge(_edge(index)) is not None

    timeout_started_ns = time.monotonic_ns()
    with sink._condition:
        controls = sink._prepare_timeout_controls_locked()
        assert len(controls) == 64
        assert sink._dropped_control_count == 2
        assert sink._reserved_queued == 64
        assert sink._queued_bytes == sum(len(control.raw) for control in controls)
    timeout_losses = [
        json.loads(control.raw)
        for control in controls
        if json.loads(control.raw)["reason"] == "close_timeout"
    ]
    assert timeout_losses
    assert all(
        row["first_observed_timestamp_ns"] >= timeout_started_ns
        and row["first_observed_timestamp_ns"] == row["last_observed_timestamp_ns"]
        for row in timeout_losses
    )

    with sink._condition:
        sink._abandoned = True
        sink._condition.notify_all()
    writer_gate.set()
    sink._writer.join(timeout=1.0)
    sink._unregister_atexit()
    assert sink._writer.is_alive() is False


def test_writer_failure_does_not_escape_or_fabricate_summary(tmp_path: Path) -> None:
    start_written = False

    def fail_after_start(fd: int, data: bytes | memoryview) -> int:
        nonlocal start_written
        if not start_written:
            start_written = True
            return os.write(fd, data)
        raise OSError("injected writer failure")

    sink = JsonlTraceSink(
        tmp_path / "trace",
        _provenance(),
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: PROCESS_UUID,
        write_function=fail_after_start,
    )
    assert sink.write_event(_received()) is not None
    result = sink.close()
    _, rows = _read_rows(sink.shard_path)

    assert result.close_outcome == "writer_failure"
    assert result.summary_written is False
    assert result.dropped_data_count == 1
    assert [row["record_type"] for row in rows] == ["process_start"]
    assert sink.diagnostic_counts["writer_failure"] == 1


def test_persistent_close_failure_publishes_state_but_not_formal_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = JsonlTraceSink(
        tmp_path / "trace",
        _provenance(),
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: PROCESS_UUID,
    )
    assert sink.write_event(_received()) is not None
    persistent_fd = sink._fd
    original_close = os.close

    def fail_persistent_close(fd: int) -> None:
        if fd == persistent_fd:
            raise OSError("injected persistent close failure")
        original_close(fd)

    monkeypatch.setattr(runtime_hooks_module.os, "close", fail_persistent_close)
    result = sink.close()
    original_close(persistent_fd)

    assert result.close_outcome == "writer_failure"
    assert result.summary_written is False
    assert sink._closed is True
    assert sink._writer.is_alive() is False
    assert sink.shard_path.read_bytes() == b""
    assert sink.incomplete_shard_path is not None
    assert sink.incomplete_shard_path.exists()
    assert sink.diagnostic_counts["writer_failure"] == 1


def test_blocked_close_keeps_valid_looking_summary_out_of_formal_namespace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    close_entered = threading.Event()
    release_close = threading.Event()
    sink = JsonlTraceSink(
        tmp_path / "trace",
        _provenance(),
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: PROCESS_UUID,
    )
    assert sink.write_event(_received()) is not None
    persistent_fd = sink._fd
    original_close = os.close

    def block_persistent_close(fd: int) -> None:
        if fd == persistent_fd:
            close_entered.set()
            release_close.wait(timeout=10.0)
        original_close(fd)

    monkeypatch.setattr(runtime_hooks_module.os, "close", block_persistent_close)
    results: list[object] = []
    closer = threading.Thread(target=lambda: results.append(sink.close()))
    closer.start()
    assert close_entered.wait(timeout=1.0)

    def fail_namespace_operation(*_args: object, **_kwargs: object) -> None:
        raise OSError("injected namespace failure")

    monkeypatch.setattr(Path, "rename", fail_namespace_operation)
    monkeypatch.setattr(Path, "unlink", fail_namespace_operation)
    closer.join(timeout=CLOSE_TIMEOUT_MS / 1000.0 + 0.2)

    assert closer.is_alive() is False
    result = results[0]
    assert result.close_outcome == "timeout"
    assert result.summary_written is False
    assert sink.shard_path.read_bytes() == b""
    assert sink.incomplete_shard_path is not None
    _, rows = _read_rows(sink.incomplete_shard_path)
    assert [row["record_type"] for row in rows] == [
        "process_start",
        "event",
        "process_summary",
    ]

    release_close.set()
    sink._writer.join(timeout=1.0)
    assert sink._writer.is_alive() is False
    assert sink.shard_path.read_bytes() == b""


def test_clock_domain_initialization_failure_never_creates_a_shard(
    tmp_path: Path,
) -> None:
    factory_called = False

    def fail_clock_domain() -> str:
        raise OSError("boot id unavailable")

    def process_uuid_factory() -> str:
        nonlocal factory_called
        factory_called = True
        return PROCESS_UUID

    with pytest.raises(OSError, match="boot id unavailable"):
        JsonlTraceSink(
            tmp_path / "trace",
            _provenance(),
            clock_domain_reader=fail_clock_domain,
            process_uuid_factory=process_uuid_factory,
        )

    assert factory_called is False
    assert list(tmp_path.iterdir()) == []


def test_fchmod_initialization_failure_closes_fd_and_removes_shard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before_fds = len(list(Path("/proc/self/fd").iterdir()))

    def fail_fchmod(_fd: int, _mode: int) -> None:
        raise OSError("injected fchmod failure")

    monkeypatch.setattr(runtime_hooks_module.os, "fchmod", fail_fchmod)
    with pytest.raises(OSError, match="injected fchmod failure"):
        JsonlTraceSink(
            tmp_path / "trace",
            _provenance(),
            clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
            process_uuid_factory=lambda: PROCESS_UUID,
        )

    after_fds = len(list(Path("/proc/self/fd").iterdir()))
    assert after_fds == before_fds
    assert list(tmp_path.iterdir()) == []


def test_runtime_hooks_fail_open_on_initialization_error_and_log_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    not_a_directory = tmp_path / "not-a-directory"
    not_a_directory.write_text("occupied", encoding="utf-8")
    config = RuntimeTraceConfig(
        export_path=not_a_directory / "trace",
        provenance=_provenance(),
    )

    hooks = RuntimeLifecycleHooks(config)

    assert hooks.enabled is False
    assert hooks.new_trace_id() is None
    for _ in range(100):
        assert hooks.emit_event(_received()) is None
    assert hooks.close() is None
    assert sum("init_failure" in record.getMessage() for record in caplog.records) == 1


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires POSIX fork")
def test_explicit_after_fork_reinitialize_creates_independent_child_shard(
    tmp_path: Path,
) -> None:
    base_path = tmp_path / "trace"
    config = RuntimeTraceConfig(export_path=base_path, provenance=_provenance())
    hooks = RuntimeLifecycleHooks(config)
    assert hooks.emit_event(_received({"process_marker": "parent_before"}))
    parent_sink = hooks._sink
    assert isinstance(parent_sink, JsonlTraceSink)

    lock_held = threading.Event()
    release_lock = threading.Event()

    def hold_inherited_condition() -> None:
        with parent_sink._condition:
            lock_held.set()
            release_lock.wait(timeout=5.0)

    holder = threading.Thread(target=hold_inherited_condition)
    holder.start()
    assert lock_held.wait(timeout=1.0)
    read_fd, write_fd = os.pipe()
    child_pid = os.fork()
    if child_pid == 0:
        os.close(read_fd)
        try:
            enabled_before = hooks.enabled
            skipped_before = hooks.emit_event(
                _received({"process_marker": "child_skipped"})
            )
            reinitialized = hooks.reinitialize_after_fork()
            child_ref = hooks.emit_event(_received({"process_marker": "child"}))
            child_result = hooks.close()
            payload = {
                "pid": os.getpid(),
                "enabled_before": enabled_before,
                "skipped_before": skipped_before is None,
                "reinitialized": reinitialized,
                "record_seq": None if child_ref is None else child_ref.record_seq,
                "summary": bool(child_result and child_result.summary_written),
            }
        except BaseException as exc:  # noqa: BLE001 - report child failure.
            payload = {"error": type(exc).__name__}
        os.write(write_fd, json.dumps(payload).encode("ascii"))
        os.close(write_fd)
        os._exit(0)

    os.close(write_fd)
    release_lock.set()
    holder.join(timeout=1.0)
    readable, _, _ = select.select([read_fd], [], [], 5.0)
    if not readable:
        os.kill(child_pid, 9)
        os.waitpid(child_pid, 0)
        pytest.fail("child blocked on inherited exporter state")
    child_payload = json.loads(os.read(read_fd, 4096))
    os.close(read_fd)
    _, child_status = os.waitpid(child_pid, 0)

    assert os.waitstatus_to_exitcode(child_status) == 0
    assert child_payload == {
        "pid": child_pid,
        "enabled_before": False,
        "skipped_before": True,
        "reinitialized": True,
        "record_seq": 0,
        "summary": True,
    }
    assert hooks.emit_event(_received({"process_marker": "parent_after"}))
    parent_result = hooks.close()
    assert parent_result is not None and parent_result.summary_written is True

    shards = sorted(tmp_path.glob("trace.rlp.*.jsonl"))
    assert len(shards) == 2
    rows_by_pid: dict[int, list[dict[str, object]]] = {}
    for shard in shards:
        _, rows = _read_rows(shard)
        rows_by_pid[int(rows[0]["pid"])] = rows
        assert rows[0]["record_type"] == "process_start"
        assert rows[-1]["record_type"] == "process_summary"
    assert set(rows_by_pid) == {os.getpid(), child_pid}
    parent_rows = rows_by_pid[os.getpid()]
    child_rows = rows_by_pid[child_pid]
    assert [
        row["record_seq"] for row in parent_rows if row["record_type"] == "event"
    ] == [0, 1]
    assert [
        row["record_seq"] for row in child_rows if row["record_type"] == "event"
    ] == [0]
    assert {
        row["metadata"]["process_marker"]
        for row in parent_rows
        if row["record_type"] == "event"
    } == {"parent_before", "parent_after"}
    assert {
        row["metadata"]["process_marker"]
        for row in child_rows
        if row["record_type"] == "event"
    } == {"child"}


def test_legacy_reader_preserves_old_stream_done_semantics(tmp_path: Path) -> None:
    legacy_path = tmp_path / "legacy.jsonl"
    legacy_path.write_text(
        json.dumps(
            {
                "request_id": "req-legacy",
                "stage": "stream_done",
                "timestamp_ms": 12.5,
                "metadata": {"observer": "vllm_runtime_hook"},
            },
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )

    events = load_legacy_jsonl(legacy_path)

    assert len(events) == 1
    assert events[0].stage is LifecycleStage.STREAM_DONE
    assert events[0].metadata == {"observer": "vllm_runtime_hook"}
    assert "schema_version" not in json.loads(legacy_path.read_text())


def test_uuid_collision_retries_are_bounded(tmp_path: Path) -> None:
    base_path = tmp_path / "trace"
    collision = Path(f"{base_path}.rlp.{PROCESS_UUID}.jsonl")
    collision.touch()

    with pytest.raises(FileExistsError, match="unique process shard"):
        JsonlTraceSink(
            base_path,
            _provenance(),
            clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
            process_uuid_factory=lambda: PROCESS_UUID,
        )
