"""Bounded Route-B scheduler exporter without destination runtime hooks.

PR-I1 owns this process-local writer and its wire state.  PR-I2 supplies the
audited vLLM call sites that invoke it.  The scheduler stream intentionally has
its own queue, sequence, loss ledger, writer thread, summary, and close result;
it shares only an explicit process identity and clock domain with lifecycle.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import os
import re
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

SCHEDULER_SCHEMA = "rlp.scheduler/v1alpha1"
SCHEDULER_RUNTIME_PROFILE_ID = "vllm-0.21-uniproc-sync-one-device-v1"
SCHEDULER_WIRE_LIMITS: dict[str, object] = {
    "artifact_bytes_max": 2_374_590_464,
    "clock_bridge_max_records": 1_801,
    "clock_bridge_records_per_writer_gap_max": 3,
    "close_timeout_ms": 5_000,
    "data_capacity_records": 1_024,
    "disk_free_margin_bytes": 67_108_864,
    "disk_free_required_bytes": 2_441_699_328,
    "max_batch_bytes": 524_288,
    "max_batch_records": 128,
    "max_loss_interval_records_per_shard": 64,
    "max_cycle_rate_per_rolling_second": 40,
    "max_cycles_in_formal_run": 72_000,
    "max_data_records_per_cycle": 4,
    "max_formal_run_duration_s": 1_800,
    "max_record_bytes_including_lf": 8_192,
    "max_writer_service_gap_ms": 2_000,
    "max_queued_bytes": 8_912_896,
    "producer_safety_factor": 2,
    "reserved_capacity_records": 64,
    "shard_mode_octal": "0600",
    "shard_path_template": "<base>.rlp-scheduler.<scheduler_shard_id>.jsonl",
    "shard_scope": "one_append_only_shard_per_scheduler_shard_id",
    "write_interval_ms": 100,
}

_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_SHARD_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_OPAQUE_ID = re.compile(r"^[!-~]{1,128}$")
_DATA_RECORD_TYPES = {
    "schedule_cycle",
    "logical_batch",
    "execution_step_start",
    "execution_step_end",
    "clock_bridge_sample",
}
_LOSS_REASONS = {
    "serialization_failure",
    "queue_overflow",
    "writer_failure",
    "close_timeout",
}

ClockFunction = Callable[[], int]
WriteFunction = Callable[[int, bytes | memoryview], int]


def _opaque(value: object, name: str, *, shard: bool = False) -> str:
    pattern = _SHARD_ID if shard else _OPAQUE_ID
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ValueError(f"{name} is outside the Route-B identifier domain")
    return value


def _hex(value: object, name: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ValueError(f"{name} is not a frozen hexadecimal identity")
    return value


def _uint64(value: object, name: str) -> int:
    if type(value) is not int or not 0 <= value <= 2**64 - 1:
        raise ValueError(f"{name} is outside uint64")
    return value


def _canonical_line(record: Mapping[str, object]) -> bytes:
    raw = (
        json.dumps(
            dict(record),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )
    if len(raw) > int(SCHEDULER_WIRE_LIMITS["max_record_bytes_including_lf"]):
        raise ValueError("scheduler record exceeds the frozen wire limit")
    return raw


@dataclass(frozen=True, slots=True)
class ProcessLocalExporterIdentity:
    """One launcher-bound identity shared by independent local streams."""

    process_instance_id: str
    clock_domain_id: str
    owner_pid: int

    def __post_init__(self) -> None:
        _opaque(self.process_instance_id, "process_instance_id")
        _hex(self.clock_domain_id, "clock_domain_id", _HEX32)
        if type(self.owner_pid) is not int or self.owner_pid <= 0:
            raise ValueError("owner_pid must be a positive process id")


@dataclass(frozen=True, slots=True)
class SchedulerShardScope:
    experiment_run_id: str
    server_instance_id: str
    scheduler_shard_id: str
    process_role: str = "engine_core"

    def __post_init__(self) -> None:
        _opaque(self.experiment_run_id, "experiment_run_id")
        _opaque(self.server_instance_id, "server_instance_id")
        _opaque(self.scheduler_shard_id, "scheduler_shard_id", shard=True)
        if self.process_role != "engine_core":
            raise ValueError("the v1 scheduler process role must be engine_core")


@dataclass(frozen=True, slots=True)
class SchedulerProvenance:
    runtime_core_commit: str
    device_plugin_commit: str
    parent_protocol_commit: str

    def __post_init__(self) -> None:
        _hex(self.runtime_core_commit, "runtime_core_commit", _HEX40)
        _hex(self.device_plugin_commit, "device_plugin_commit", _HEX40)
        _hex(self.parent_protocol_commit, "parent_protocol_commit", _HEX40)


@dataclass(frozen=True, slots=True)
class SchedulerExporterConfig:
    base_path: Path | None
    scope: SchedulerShardScope | None = None
    provenance: SchedulerProvenance | None = None
    runtime_profile_id: str = SCHEDULER_RUNTIME_PROFILE_ID

    @property
    def enabled(self) -> bool:
        return self.base_path is not None and self.scope is not None and self.provenance is not None

    def validate_enabled(self) -> None:
        if not self.enabled:
            raise ValueError("enabled scheduler export requires path, scope, and provenance")
        if self.runtime_profile_id != SCHEDULER_RUNTIME_PROFILE_ID:
            raise ValueError("unsupported scheduler runtime profile")


@dataclass(frozen=True, slots=True)
class SchedulerCycleRef:
    cycle_seq: int
    schedule_cycle_id: str
    logical_batch_id: str
    execution_step_id: str


@dataclass(frozen=True, slots=True)
class SchedulerCloseResult:
    close_outcome: str
    summary_written: bool
    attempted_data_count: int
    dropped_data_count: int
    dropped_control_count: int
    writer_failure_count: int
    shard_path: Path | None

    @property
    def evidence_complete(self) -> bool:
        return (
            self.close_outcome == "drained"
            and self.summary_written
            and self.dropped_data_count == 0
            and self.dropped_control_count == 0
            and self.writer_failure_count == 0
            and self.shard_path is not None
        )


@dataclass(frozen=True, slots=True)
class _QueuedRecord:
    raw: bytes
    record_type: str
    record_seq: int | None
    reserved: bool


@dataclass(slots=True)
class _OpenLoss:
    reason: str
    first_record_seq: int
    last_record_seq: int
    counts: dict[str, int]
    first_timestamp_ns: int
    last_timestamp_ns: int


class NullSchedulerProfileExporter:
    """Default-off scheduler stream: no identity, IDs, queue, clock, or file."""

    enabled = False
    shard_path: Path | None = None
    committed_shard_path: Path | None = None

    def begin_cycle(self, _fields: Mapping[str, object]) -> None:
        return None

    def write_logical_batch(
        self, _reference: SchedulerCycleRef, _fields: Mapping[str, object]
    ) -> bool:
        return False

    def write_execution_step_start(
        self, _reference: SchedulerCycleRef, _fields: Mapping[str, object]
    ) -> bool:
        return False

    def write_execution_step_end(
        self, _reference: SchedulerCycleRef, _fields: Mapping[str, object]
    ) -> bool:
        return False

    def write_clock_bridge_sample(self, _fields: Mapping[str, object]) -> bool:
        return False

    def close(self) -> None:
        return None


class SchedulerProfileExporter:
    """Independent bounded writer for one scheduler shard."""

    enabled = True

    def __init__(
        self,
        config: SchedulerExporterConfig,
        identity: ProcessLocalExporterIdentity,
        *,
        clock_ns: ClockFunction = time.monotonic_ns,
        write_function: WriteFunction = os.write,
        writer_start_gate: threading.Event | None = None,
    ) -> None:
        config.validate_enabled()
        if identity.owner_pid != os.getpid():
            raise ValueError("scheduler identity belongs to another process")
        assert config.base_path is not None
        assert config.scope is not None
        assert config.provenance is not None
        self.config = config
        self.identity = identity
        self.scope = config.scope
        self.provenance = config.provenance
        self._clock_ns = clock_ns
        self._write_function = write_function
        self._writer_start_gate = writer_start_gate
        self._owner_pid = identity.owner_pid
        self.shard_path = Path(
            f"{config.base_path}.rlp-scheduler.{self.scope.scheduler_shard_id}.jsonl"
        )
        self.incomplete_shard_path: Path | None = None
        self._reservation_identity: tuple[int, int] | None = None
        self._started_monotonic_ns = _uint64(clock_ns(), "started_monotonic_ns")

        self._condition = threading.Condition()
        self._close_lock = threading.Lock()
        self._writer_ready = threading.Event()
        self._writer_done = threading.Event()
        self._queue: deque[_QueuedRecord] = deque()
        self._queued_bytes = 0
        self._ordinary_queued = 0
        self._reserved_queued = 0
        self._next_record_seq = 0
        self._next_cycle_seq = 0
        self._next_batch_seq = 0
        self._next_execution_start_seq = 0
        self._next_execution_end_seq = 0
        self._next_clock_sample_seq = 0
        self._next_loss_interval_seq = 0
        self._open_loss: _OpenLoss | None = None
        self._attempted_data_count = 0
        self._written_counts = {record_type: 0 for record_type in _DATA_RECORD_TYPES}
        self._written_loss_interval_count = 0
        self._dropped_data_count = 0
        self._dropped_control_count = 0
        self._writer_failure_count = 0
        self._closing = False
        self._closed = False
        self._close_timed_out = False
        self._summary_written = False
        self._init_error: Exception | None = None
        self._close_result: SchedulerCloseResult | None = None
        # CPython executes one dict.setdefault call while holding the GIL. It
        # provides one immutable completion winner even when close() has hit
        # its deadline and cannot safely wait for the writer's condition.
        self._completion_claim: dict[str, SchedulerCloseResult] = {}
        self._content_hash = hashlib.sha256()
        self._fd = -1

        self._writer = threading.Thread(
            target=self._writer_main,
            name=f"rlp-scheduler-writer-{self.scope.scheduler_shard_id}",
            daemon=True,
        )
        self._writer.start()
        timeout = int(SCHEDULER_WIRE_LIMITS["close_timeout_ms"]) / 1_000
        if not self._writer_ready.wait(timeout):
            with self._condition:
                self._close_timed_out = True
                self._closing = True
                self._condition.notify_all()
            raise TimeoutError("scheduler writer initialization timed out")
        if self._init_error is not None:
            raise self._init_error
        self._atexit_registered = True
        atexit.register(self.close)

    def begin_cycle(self, fields: Mapping[str, object]) -> SchedulerCycleRef | None:
        if not self._usable():
            return None
        with self._condition:
            if self._closing or self._closed:
                return None
            cycle_seq = self._next_cycle_seq
            self._next_cycle_seq += 1
            reference = SchedulerCycleRef(
                cycle_seq=cycle_seq,
                schedule_cycle_id=(
                    f"{self.scope.scheduler_shard_id}:cycle:{cycle_seq}"
                ),
                logical_batch_id=(
                    f"{self.scope.scheduler_shard_id}:batch:{cycle_seq}"
                ),
                execution_step_id=(
                    f"{self.scope.scheduler_shard_id}:step:{cycle_seq}"
                ),
            )
            record = {
                **dict(fields),
                "schema_version": SCHEDULER_SCHEMA,
                "record_type": "schedule_cycle",
                "scheduler_shard_id": self.scope.scheduler_shard_id,
                "cycle_seq": cycle_seq,
                "schedule_cycle_id": reference.schedule_cycle_id,
                "logical_batch_id": reference.logical_batch_id,
            }
            self._emit_data_locked("schedule_cycle", record)
            return reference

    def write_logical_batch(
        self, reference: SchedulerCycleRef, fields: Mapping[str, object]
    ) -> bool:
        if not self._usable():
            return False
        with self._condition:
            if self._closing or self._closed:
                return False
            batch_seq = self._next_batch_seq
            self._next_batch_seq += 1
            record = {
                **dict(fields),
                "schema_version": SCHEDULER_SCHEMA,
                "record_type": "logical_batch",
                "scheduler_shard_id": self.scope.scheduler_shard_id,
                "batch_seq": batch_seq,
                "logical_batch_id": reference.logical_batch_id,
                "schedule_cycle_id": reference.schedule_cycle_id,
                "execution_step_id": reference.execution_step_id,
            }
            return self._emit_data_locked("logical_batch", record)

    def write_execution_step_start(
        self, reference: SchedulerCycleRef, fields: Mapping[str, object]
    ) -> bool:
        if not self._usable():
            return False
        with self._condition:
            if self._closing or self._closed:
                return False
            step_seq = self._next_execution_start_seq
            self._next_execution_start_seq += 1
            record = {
                **dict(fields),
                "schema_version": SCHEDULER_SCHEMA,
                "record_type": "execution_step_start",
                "scheduler_shard_id": self.scope.scheduler_shard_id,
                "execution_step_seq": step_seq,
                "execution_step_id": reference.execution_step_id,
                "logical_batch_id": reference.logical_batch_id,
            }
            return self._emit_data_locked("execution_step_start", record)

    def write_execution_step_end(
        self, reference: SchedulerCycleRef, fields: Mapping[str, object]
    ) -> bool:
        if not self._usable():
            return False
        with self._condition:
            if self._closing or self._closed:
                return False
            step_seq = self._next_execution_end_seq
            self._next_execution_end_seq += 1
            record = {
                **dict(fields),
                "schema_version": SCHEDULER_SCHEMA,
                "record_type": "execution_step_end",
                "scheduler_shard_id": self.scope.scheduler_shard_id,
                "execution_step_seq": step_seq,
                "execution_step_id": reference.execution_step_id,
                "logical_batch_id": reference.logical_batch_id,
            }
            return self._emit_data_locked("execution_step_end", record)

    def write_clock_bridge_sample(self, fields: Mapping[str, object]) -> bool:
        if not self._usable():
            return False
        with self._condition:
            if self._closing or self._closed:
                return False
            sample_sequence = self._next_clock_sample_seq
            self._next_clock_sample_seq += 1
            record = {
                **dict(fields),
                "schema_version": SCHEDULER_SCHEMA,
                "record_type": "clock_bridge_sample",
                "scheduler_shard_id": self.scope.scheduler_shard_id,
                "sample_sequence": sample_sequence,
                "clock_domain_id": self.identity.clock_domain_id,
            }
            return self._emit_data_locked("clock_bridge_sample", record)

    def close(self) -> SchedulerCloseResult | None:
        if not self._usable():
            return None
        timeout = int(SCHEDULER_WIRE_LIMITS["close_timeout_ms"]) / 1_000
        deadline = time.monotonic() + timeout
        claimed = self._claimed_close_result()
        if claimed is not None:
            self._unregister_atexit()
            return claimed
        if not self._close_lock.acquire(timeout=max(0.0, deadline - time.monotonic())):
            result = self._publish_timeout()
            self._unregister_atexit()
            return result
        try:
            if not self._condition.acquire(
                timeout=max(0.0, deadline - time.monotonic())
            ):
                return self._publish_timeout()
            try:
                claimed = self._claimed_close_result()
                if claimed is not None:
                    return claimed
                if self._closed:
                    result, _ = self._claim_close_result("writer_failure", False)
                    return result
                self._seal_loss_locked()
                self._closing = True
                self._condition.notify_all()
            finally:
                self._condition.release()
            if not self._writer_done.wait(max(0.0, deadline - time.monotonic())):
                return self._publish_timeout()
            claimed = self._claimed_close_result()
            if claimed is not None:
                return claimed
            result, _ = self._claim_close_result("writer_failure", False)
            return result
        finally:
            self._unregister_atexit()
            self._close_lock.release()

    @property
    def committed_shard_path(self) -> Path | None:
        """Return the formal shard only after one immutable complete close."""

        result = self._claimed_close_result()
        if result is not None and result.evidence_complete:
            return self.shard_path
        return None

    def __enter__(self) -> SchedulerProfileExporter:  # noqa: PYI034
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def _usable(self) -> bool:
        return os.getpid() == self._owner_pid

    def _emit_data_locked(
        self, record_type: str, record: dict[str, object]
    ) -> bool:
        if self._closing or self._closed:
            return False
        record_seq = self._next_record_seq
        self._next_record_seq += 1
        self._attempted_data_count += 1
        record["record_seq"] = record_seq
        observed_ns = self._observation_time(record)
        try:
            raw = _canonical_line(record)
        except Exception:  # noqa: BLE001 - serving remains fail-open.
            self._note_drop_locked(
                record_seq, record_type, "serialization_failure", observed_ns
            )
            return False
        if not self._can_enqueue_locked(raw, reserved=False):
            self._note_drop_locked(
                record_seq, record_type, "queue_overflow", observed_ns
            )
            return False
        self._seal_loss_locked()
        if self._enqueue_locked(_QueuedRecord(raw, record_type, record_seq, False)):
            return True
        self._note_drop_locked(
            record_seq, record_type, "queue_overflow", observed_ns
        )
        return False

    def _observation_time(self, record: Mapping[str, object]) -> int:
        for field in (
            "cycle_end_monotonic_ns",
            "final_result_monotonic_ns",
            "dispatch_monotonic_ns",
            "monotonic_after_ns",
        ):
            value = record.get(field)
            if type(value) is int and 0 <= value <= 2**64 - 1:
                return value
        try:
            return _uint64(self._clock_ns(), "drop_observation_ns")
        except Exception:  # noqa: BLE001 - diagnostic fallback only.
            return time.monotonic_ns()

    def _can_enqueue_locked(self, raw: bytes, *, reserved: bool) -> bool:
        if self._closing or self._closed or self._close_timed_out:
            return False
        if self._queued_bytes + len(raw) > int(
            SCHEDULER_WIRE_LIMITS["max_queued_bytes"]
        ):
            return False
        if reserved:
            return self._reserved_queued < int(
                SCHEDULER_WIRE_LIMITS["reserved_capacity_records"]
            )
        return self._ordinary_queued < int(
            SCHEDULER_WIRE_LIMITS["data_capacity_records"]
        )

    def _enqueue_locked(self, queued: _QueuedRecord) -> bool:
        if not self._can_enqueue_locked(queued.raw, reserved=queued.reserved):
            return False
        self._queue.append(queued)
        self._queued_bytes += len(queued.raw)
        if queued.reserved:
            self._reserved_queued += 1
        else:
            self._ordinary_queued += 1
        self._condition.notify()
        return True

    def _note_drop_locked(
        self,
        record_seq: int,
        record_type: str,
        reason: str,
        observed_ns: int,
    ) -> None:
        if reason not in _LOSS_REASONS:
            reason = "serialization_failure"
        self._dropped_data_count += 1
        counts = {item: 0 for item in _DATA_RECORD_TYPES}
        counts[record_type] = 1
        current = self._open_loss
        if (
            current is not None
            and current.reason == reason
            and record_seq == current.last_record_seq + 1
        ):
            current.last_record_seq = record_seq
            current.counts[record_type] += 1
            current.last_timestamp_ns = observed_ns
            return
        self._seal_loss_locked()
        self._open_loss = _OpenLoss(
            reason,
            record_seq,
            record_seq,
            counts,
            observed_ns,
            observed_ns,
        )

    def _seal_loss_locked(self) -> None:
        loss = self._open_loss
        if loss is None:
            return
        self._open_loss = None
        loss_seq = self._next_loss_interval_seq
        self._next_loss_interval_seq += 1
        record = {
            "schema_version": SCHEDULER_SCHEMA,
            "record_type": "loss_interval",
            "scheduler_shard_id": self.scope.scheduler_shard_id,
            "loss_interval_seq": loss_seq,
            "loss_interval_id": (
                f"{self.scope.scheduler_shard_id}:loss:{loss_seq}"
            ),
            "reason": loss.reason,
            "first_dropped_record_seq": loss.first_record_seq,
            "last_dropped_record_seq": loss.last_record_seq,
            "dropped_count": loss.last_record_seq - loss.first_record_seq + 1,
            "schedule_cycle_count": loss.counts["schedule_cycle"],
            "logical_batch_count": loss.counts["logical_batch"],
            "execution_step_start_count": loss.counts["execution_step_start"],
            "execution_step_end_count": loss.counts["execution_step_end"],
            "clock_bridge_sample_count": loss.counts["clock_bridge_sample"],
            "first_observed_monotonic_ns": loss.first_timestamp_ns,
            "last_observed_monotonic_ns": loss.last_timestamp_ns,
        }
        try:
            raw = _canonical_line(record)
        except Exception:  # noqa: BLE001 - control loss invalidates evidence.
            self._dropped_control_count += 1
            return
        if not self._enqueue_locked(_QueuedRecord(raw, "loss_interval", None, True)):
            self._dropped_control_count += 1

    def _start_record(self) -> dict[str, object]:
        return {
            "schema_version": SCHEDULER_SCHEMA,
            "record_type": "scheduler_start",
            "experiment_run_id": self.scope.experiment_run_id,
            "server_instance_id": self.scope.server_instance_id,
            "process_instance_id": self.identity.process_instance_id,
            "scheduler_shard_id": self.scope.scheduler_shard_id,
            "process_role": self.scope.process_role,
            "profile_stream": "scheduler",
            "started_monotonic_ns": self._started_monotonic_ns,
            "clock_source": "CLOCK_MONOTONIC",
            "clock_domain_id": self.identity.clock_domain_id,
            "runtime_core_commit": self.provenance.runtime_core_commit,
            "device_plugin_commit": self.provenance.device_plugin_commit,
            "parent_protocol_commit": self.provenance.parent_protocol_commit,
            "runtime_profile_id": self.config.runtime_profile_id,
            "limits": dict(SCHEDULER_WIRE_LIMITS),
        }

    def _summary_record(self, ended_ns: int) -> dict[str, object]:
        attempted = self._attempted_data_count
        return {
            "schema_version": SCHEDULER_SCHEMA,
            "record_type": "scheduler_summary",
            "experiment_run_id": self.scope.experiment_run_id,
            "server_instance_id": self.scope.server_instance_id,
            "process_instance_id": self.identity.process_instance_id,
            "scheduler_shard_id": self.scope.scheduler_shard_id,
            "process_role": self.scope.process_role,
            "profile_stream": "scheduler",
            "ended_monotonic_ns": ended_ns,
            "attempted_data_count": attempted,
            "written_schedule_cycle_count": self._written_counts["schedule_cycle"],
            "written_logical_batch_count": self._written_counts["logical_batch"],
            "written_execution_step_start_count": self._written_counts[
                "execution_step_start"
            ],
            "written_execution_step_end_count": self._written_counts[
                "execution_step_end"
            ],
            "written_clock_bridge_sample_count": self._written_counts[
                "clock_bridge_sample"
            ],
            "written_loss_interval_count": self._written_loss_interval_count,
            "dropped_data_count": self._dropped_data_count,
            "dropped_control_count": self._dropped_control_count,
            "first_data_record_seq": 0 if attempted else None,
            "last_data_record_seq": attempted - 1 if attempted else None,
            "writer_failure_count": self._writer_failure_count,
            "close_outcome": "drained",
            "content_sha256": self._content_hash.hexdigest(),
        }

    def _writer_main(self) -> None:
        initialized = False
        try:
            self._initialize_writer()
            start_raw = _canonical_line(self._start_record())
            self._write_all(start_raw)
            self._content_hash.update(start_raw)
            initialized = True
            self._writer_ready.set()
            if self._writer_start_gate is not None:
                self._writer_start_gate.wait()

            while True:
                batch: list[_QueuedRecord] = []
                with self._condition:
                    while not self._queue and not self._closing:
                        self._condition.wait(
                            int(SCHEDULER_WIRE_LIMITS["write_interval_ms"]) / 1_000
                        )
                    batch_bytes = 0
                    while self._queue and len(batch) < int(
                        SCHEDULER_WIRE_LIMITS["max_batch_records"]
                    ):
                        candidate = self._queue[0]
                        if batch and batch_bytes + len(candidate.raw) > int(
                            SCHEDULER_WIRE_LIMITS["max_batch_bytes"]
                        ):
                            break
                        queued = self._queue.popleft()
                        batch.append(queued)
                        batch_bytes += len(queued.raw)
                        self._queued_bytes -= len(queued.raw)
                        if queued.reserved:
                            self._reserved_queued -= 1
                        else:
                            self._ordinary_queued -= 1
                    should_finish = self._closing and not self._queue and not batch

                for queued in batch:
                    self._write_all(queued.raw)
                    self._content_hash.update(queued.raw)
                    with self._condition:
                        if queued.record_type == "loss_interval":
                            self._written_loss_interval_count += 1
                        else:
                            self._written_counts[queued.record_type] += 1
                if should_finish:
                    break

            if self._claimed_close_result() is None and not self._close_timed_out:
                ended_ns = _uint64(self._clock_ns(), "ended_monotonic_ns")
                summary_raw = _canonical_line(self._summary_record(ended_ns))
                if self._claimed_close_result() is None and not self._close_timed_out:
                    self._write_all(summary_raw)
                    os.fsync(self._fd)
                    self._close_writer_fd()
                    self._summary_written = True
                    published = self._publish_completed_shard()
                    if not published and self._claimed_close_result() is None:
                        raise OSError("scheduler shard publication failed")
        except Exception as exc:  # noqa: BLE001 - writer is evidence-only.
            with self._condition:
                self._writer_failure_count += 1
                self._summary_written = False
                if not self._writer_ready.is_set():
                    self._init_error = exc
                self._claim_close_result("writer_failure", False)
        finally:
            if self._fd >= 0:
                try:
                    self._close_writer_fd()
                except OSError:
                    with self._condition:
                        self._writer_failure_count += 1
                        self._summary_written = False
                        self._claim_close_result("writer_failure", False)
            if not initialized:
                self._remove_failed_initialization_artifacts()
            with self._condition:
                self._closed = True
                if self._closing and self._claimed_close_result() is None:
                    self._claim_close_result("writer_failure", False)
                self._condition.notify_all()
            self._writer_ready.set()
            self._writer_done.set()

    def _initialize_writer(self) -> None:
        self.shard_path.parent.mkdir(parents=True, exist_ok=True)
        cloexec = getattr(os, "O_CLOEXEC", 0)
        reservation_fd = os.open(
            self.shard_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | cloexec,
            0o600,
        )
        try:
            os.fchmod(reservation_fd, 0o600)
            reservation_stat = os.fstat(reservation_fd)
            self._reservation_identity = (
                reservation_stat.st_dev,
                reservation_stat.st_ino,
            )
        finally:
            os.close(reservation_fd)

        incomplete = Path(
            f"{self.shard_path}.incomplete.{self._owner_pid}."
            f"{self._started_monotonic_ns}"
        )
        self.incomplete_shard_path = incomplete
        self._fd = os.open(
            incomplete,
            os.O_CREAT | os.O_EXCL | os.O_APPEND | os.O_WRONLY | cloexec,
            0o600,
        )
        os.fchmod(self._fd, 0o600)

    def _close_writer_fd(self) -> None:
        fd = self._fd
        self._fd = -1
        if fd >= 0:
            os.close(fd)

    def _publish_completed_shard(self) -> bool:
        if self._claimed_close_result() is not None or self._close_timed_out:
            return False
        source = self.incomplete_shard_path
        identity = self._reservation_identity
        if source is None or identity is None or not source.exists():
            return False
        try:
            formal_stat = os.stat(self.shard_path, follow_symlinks=False)
        except OSError:
            return False
        if (formal_stat.st_dev, formal_stat.st_ino) != identity:
            return False

        os.replace(source, self.shard_path)
        result, won = self._claim_close_result("drained", True)
        if won:
            self.incomplete_shard_path = None
            self._reservation_identity = None
            self._close_result = result
            return True

        self._retract_late_publication(source)
        self._summary_written = False
        return False

    def _retract_late_publication(self, incomplete: Path) -> None:
        """Replace a late formal shard with an empty reservation atomically."""

        reservation = Path(
            f"{self.shard_path}.reservation.{self._owner_pid}."
            f"{time.monotonic_ns()}"
        )
        reservation_fd = -1
        try:
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
            flags |= getattr(os, "O_CLOEXEC", 0)
            reservation_fd = os.open(reservation, flags, 0o600)
            os.fchmod(reservation_fd, 0o600)
            reservation_stat = os.fstat(reservation_fd)
            os.close(reservation_fd)
            reservation_fd = -1
            os.link(self.shard_path, incomplete)
            os.replace(reservation, self.shard_path)
            self._reservation_identity = (
                reservation_stat.st_dev,
                reservation_stat.st_ino,
            )
            self.incomplete_shard_path = incomplete
        except OSError:
            self._invalidate_unretracted_formal_shard()
        finally:
            if reservation_fd >= 0:
                try:
                    os.close(reservation_fd)
                except OSError:
                    pass
            try:
                reservation.unlink(missing_ok=True)
            except OSError:
                pass

    def _invalidate_unretracted_formal_shard(self) -> None:
        """Make a late-published shard structurally invalid as a last resort."""

        fd = -1
        try:
            flags = os.O_APPEND | os.O_WRONLY | getattr(os, "O_CLOEXEC", 0)
            fd = os.open(self.shard_path, flags)
            os.write(fd, b"\n")
            os.fsync(fd)
        except OSError:
            pass
        finally:
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass

    def _remove_failed_initialization_artifacts(self) -> None:
        incomplete = self.incomplete_shard_path
        if incomplete is not None:
            try:
                incomplete.unlink(missing_ok=True)
            except OSError:
                pass
        identity = self._reservation_identity
        if identity is None:
            return
        try:
            current = os.stat(self.shard_path, follow_symlinks=False)
            if (current.st_dev, current.st_ino) == identity:
                self.shard_path.unlink(missing_ok=True)
        except OSError:
            pass

    def _write_all(self, raw: bytes) -> None:
        view = memoryview(raw)
        while view:
            written = self._write_function(self._fd, view)
            if type(written) is not int or written <= 0 or written > len(view):
                raise OSError("scheduler writer made no valid progress")
            view = view[written:]

    def _publish_timeout(self) -> SchedulerCloseResult:
        result, won = self._claim_close_result("timeout", False)
        if won:
            self._close_timed_out = True
            self._closing = True
            if self._condition.acquire(blocking=False):
                try:
                    self._condition.notify_all()
                finally:
                    self._condition.release()
        return result

    def _claimed_close_result(self) -> SchedulerCloseResult | None:
        return self._completion_claim.get("result")

    def _claim_close_result(
        self, outcome: str, summary_written: bool
    ) -> tuple[SchedulerCloseResult, bool]:
        candidate = self._result(outcome, summary_written)
        winner = self._completion_claim.setdefault("result", candidate)
        self._close_result = winner
        return winner, winner is candidate

    def _unregister_atexit(self) -> None:
        if self._atexit_registered:
            atexit.unregister(self.close)
            self._atexit_registered = False

    def _result(
        self, outcome: str, summary_written: bool
    ) -> SchedulerCloseResult:
        return SchedulerCloseResult(
            close_outcome=outcome,
            summary_written=summary_written,
            attempted_data_count=self._attempted_data_count,
            dropped_data_count=self._dropped_data_count,
            dropped_control_count=self._dropped_control_count,
            writer_failure_count=self._writer_failure_count,
            shard_path=self.shard_path,
        )


def create_scheduler_profile_exporter(
    config: SchedulerExporterConfig,
    identity: ProcessLocalExporterIdentity | None = None,
    **kwargs: object,
) -> SchedulerProfileExporter | NullSchedulerProfileExporter:
    """Construct the optional stream without letting evidence break serving."""

    if not config.enabled:
        return NullSchedulerProfileExporter()
    if identity is None:
        return NullSchedulerProfileExporter()
    try:
        return SchedulerProfileExporter(config, identity, **kwargs)
    except Exception:  # noqa: BLE001 - initialization is serving-fail-open.
        return NullSchedulerProfileExporter()
