"""Default-off KV-recovery runtime adapters and strict normalization.

The classes in this module contain no activation path.  They are constructed
only by explicit callers and require the exact runtime ABI plus already-emitted
base lifecycle identities.  Serving-facing callbacks are fail-open; the
bounded profile ledger and normalizer fail formal evidence closed.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from vllm_request_lifecycle_profiler.kv_recovery_profile_protocol import (
    MAPPING_SHA256,
    MAX_PROFILE_DATA_RECORDS,
    PROFILE_ID,
    PROFILE_SHA256,
    KVRecoveryProfileConfig,
    LossReason,
    ProfileLossInterval,
    ProfileRecord,
    ProfileRecordType,
)
from vllm_request_lifecycle_profiler.runtime_hooks import RuntimeLifecycleHooks
from vllm_request_lifecycle_profiler.runtime_protocol import (
    KV_RECOVERY_COMMUNICATION_MODE,
    KV_RECOVERY_H2D_EVIDENCE,
    EdgeDraft,
    EventDraft,
)

_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_EVENT_ID = re.compile(r"^[0-9a-f]{32}:e:(0|[1-9][0-9]{0,19})$")
_UINT64_MAX = 2**64 - 1


def _require_hex32(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _HEX32.fullmatch(value):
        raise ValueError(f"{field_name} must be 32 lowercase hexadecimal characters")
    return value


def _require_event_id(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _EVENT_ID.fullmatch(value):
        raise ValueError(f"{field_name} must be a canonical base event ID")
    return value


def _is_uint64(value: object) -> bool:
    return type(value) is int and 0 <= value <= _UINT64_MAX


@dataclass(frozen=True)
class RequestLifecycleIdentity:
    """Exact base lifecycle identity owned by the base runtime adapter."""

    trace_id: str
    engine_lifecycle_id: str
    runtime_request_id: str
    sample_index: int = 0

    def __post_init__(self) -> None:
        _require_hex32(self.trace_id, "trace_id")
        if self.engine_lifecycle_id != f"{self.trace_id}:e:{self.sample_index}":
            raise ValueError("engine_lifecycle_id does not match trace/sample")
        if (
            not isinstance(self.runtime_request_id, str)
            or not self.runtime_request_id.isascii()
            or not self.runtime_request_id.isprintable()
            or not 1 <= len(self.runtime_request_id.encode("ascii")) <= 128
        ):
            raise ValueError("runtime_request_id is not bounded printable ASCII")
        if self.sample_index != 0:
            raise ValueError("KV-recovery v1alpha1 requires sample_index=0")


@dataclass(frozen=True)
class BaseEventRef:
    """ID and exact timestamp returned by an already-emitted base event."""

    event_id: str
    timestamp_ns: int

    def __post_init__(self) -> None:
        _require_event_id(self.event_id, "event_id")
        if not _is_uint64(self.timestamp_ns):
            raise ValueError("timestamp_ns must be a uint64")


class BaseLifecycleBridge(Protocol):
    """Lookup interface for IDs captured by real base lifecycle emitters."""

    def request_identity(
        self, runtime_request_id: str
    ) -> RequestLifecycleIdentity | None: ...

    def preempted_event(
        self, runtime_request_id: str, recovery_epoch: int
    ) -> BaseEventRef | None: ...

    def admission_started_event(
        self, runtime_request_id: str, recovery_epoch: int
    ) -> BaseEventRef | None: ...

    def resumed_event(
        self, runtime_request_id: str, recovery_epoch: int
    ) -> BaseEventRef | None: ...

    def first_compute_event(
        self, runtime_request_id: str, recovery_epoch: int
    ) -> BaseEventRef | None: ...


@dataclass
class _EmittedBaseEpisode:
    preempted: BaseEventRef
    requeued: BaseEventRef
    queue_span_id: str
    admission_started: BaseEventRef | None = None
    admission_span_id: str | None = None
    resumed: BaseEventRef | None = None
    first_compute: BaseEventRef | None = None


class RuntimeBaseLifecycleBridge:
    """Emit and retain the exact P0 recovery boundaries used by the adapter."""

    def __init__(
        self, hooks: RuntimeLifecycleHooks, *, capacity: int = MAX_PROFILE_DATA_RECORDS
    ) -> None:
        if type(capacity) is not int or capacity < 1:
            raise ValueError("capacity must be a positive integer")
        self._hooks = hooks
        self._capacity = capacity
        self._lock = threading.Lock()
        self._identities: dict[str, RequestLifecycleIdentity] = {}
        self._episodes: dict[tuple[str, int], _EmittedBaseEpisode] = {}

    def register_request(self, identity: RequestLifecycleIdentity) -> bool:
        with self._lock:
            current = self._identities.get(identity.runtime_request_id)
            if current is not None:
                return current == identity
            if len(self._identities) >= self._capacity:
                return False
            self._identities[identity.runtime_request_id] = identity
            return True

    def request_identity(
        self, runtime_request_id: str
    ) -> RequestLifecycleIdentity | None:
        with self._lock:
            return self._identities.get(runtime_request_id)

    def emit_preempted_and_requeued(
        self,
        runtime_request_id: str,
        recovery_epoch: int,
        *,
        timestamp_ns: int,
        active_span_start_event_id: str,
        active_span_id: str,
        prompt_tokens_computed: int,
        prefill_chunk_count: int,
    ) -> BaseEventRef | None:
        """Emit the committed old-epoch close and new-epoch queue start."""

        with self._lock:
            identity = self._identities.get(runtime_request_id)
            key = (runtime_request_id, recovery_epoch)
            if (
                identity is None
                or recovery_epoch < 1
                or key in self._episodes
                or len(self._episodes) >= self._capacity
            ):
                return None
            queue_span_id = self._hooks.new_span_id()
            if queue_span_id is None:
                return None
            preempted = self._hooks.emit_event(
                EventDraft(
                    trace_id=identity.trace_id,
                    lifecycle_id=identity.engine_lifecycle_id,
                    parent_lifecycle_id=f"{identity.trace_id}:r",
                    scope="engine_sample",
                    component="engine_core",
                    event_name="preempted",
                    timestamp_ns=timestamp_ns,
                    preemption_epoch=recovery_epoch - 1,
                    end_span_id=active_span_id,
                    sample_index=identity.sample_index,
                    metadata={
                        "prompt_tokens_computed": prompt_tokens_computed,
                        "prefill_chunk_count": prefill_chunk_count,
                    },
                )
            )
            if preempted is None:
                return None
            if (
                self._hooks.emit_edge(
                    EdgeDraft(
                        trace_id=identity.trace_id,
                        from_event_id=active_span_start_event_id,
                        to_event_id=preempted.record_id,
                        edge_kind="program_order",
                        evidence_source="instrumented_execution_context",
                    )
                )
                is None
            ):
                return None
            requeued = self._hooks.emit_event(
                EventDraft(
                    trace_id=identity.trace_id,
                    lifecycle_id=identity.engine_lifecycle_id,
                    parent_lifecycle_id=f"{identity.trace_id}:r",
                    scope="engine_sample",
                    component="engine_core",
                    event_name="requeued",
                    timestamp_ns=timestamp_ns,
                    preemption_epoch=recovery_epoch,
                    start_span_id=queue_span_id,
                    sample_index=identity.sample_index,
                )
            )
            if requeued is None:
                return None
            if (
                self._hooks.emit_edge(
                    EdgeDraft(
                        trace_id=identity.trace_id,
                        from_event_id=preempted.record_id,
                        to_event_id=requeued.record_id,
                        edge_kind="program_order",
                        evidence_source="instrumented_execution_context",
                    )
                )
                is None
            ):
                return None
            preempted_ref = BaseEventRef(preempted.record_id, timestamp_ns)
            self._episodes[key] = _EmittedBaseEpisode(
                preempted=preempted_ref,
                requeued=BaseEventRef(requeued.record_id, timestamp_ns),
                queue_span_id=queue_span_id,
            )
            return preempted_ref

    def emit_admission_started(
        self,
        runtime_request_id: str,
        recovery_epoch: int,
        *,
        timestamp_ns: int,
    ) -> BaseEventRef | None:
        with self._lock:
            identity = self._identities.get(runtime_request_id)
            episode = self._episodes.get((runtime_request_id, recovery_epoch))
            if (
                identity is None
                or episode is None
                or episode.admission_started is not None
            ):
                return None
            admission_span_id = self._hooks.new_span_id()
            if admission_span_id is None:
                return None
            emitted = self._hooks.emit_event(
                EventDraft(
                    trace_id=identity.trace_id,
                    lifecycle_id=identity.engine_lifecycle_id,
                    parent_lifecycle_id=f"{identity.trace_id}:r",
                    scope="engine_sample",
                    component="engine_core",
                    event_name="admission_started",
                    timestamp_ns=timestamp_ns,
                    preemption_epoch=recovery_epoch,
                    start_span_id=admission_span_id,
                    end_span_id=episode.queue_span_id,
                    sample_index=identity.sample_index,
                )
            )
            if emitted is None:
                return None
            if (
                self._hooks.emit_edge(
                    EdgeDraft(
                        trace_id=identity.trace_id,
                        from_event_id=episode.requeued.event_id,
                        to_event_id=emitted.record_id,
                        edge_kind="program_order",
                        evidence_source="instrumented_execution_context",
                    )
                )
                is None
            ):
                return None
            result = BaseEventRef(emitted.record_id, timestamp_ns)
            episode.admission_started = result
            episode.admission_span_id = admission_span_id
            return result

    def emit_resumed(
        self,
        runtime_request_id: str,
        recovery_epoch: int,
        *,
        timestamp_ns: int,
        prompt_tokens_total: int,
        prompt_tokens_cached: int,
        prompt_tokens_to_compute: int,
    ) -> BaseEventRef | None:
        with self._lock:
            identity = self._identities.get(runtime_request_id)
            episode = self._episodes.get((runtime_request_id, recovery_epoch))
            if (
                identity is None
                or episode is None
                or episode.admission_started is None
                or episode.admission_span_id is None
                or episode.resumed is not None
            ):
                return None
            emitted = self._hooks.emit_event(
                EventDraft(
                    trace_id=identity.trace_id,
                    lifecycle_id=identity.engine_lifecycle_id,
                    parent_lifecycle_id=f"{identity.trace_id}:r",
                    scope="engine_sample",
                    component="engine_core",
                    event_name="resumed",
                    timestamp_ns=timestamp_ns,
                    preemption_epoch=recovery_epoch,
                    end_span_id=episode.admission_span_id,
                    sample_index=identity.sample_index,
                    metadata={
                        "prompt_tokens_total": prompt_tokens_total,
                        "prompt_tokens_cached": prompt_tokens_cached,
                        "prompt_tokens_to_compute": prompt_tokens_to_compute,
                    },
                )
            )
            if emitted is None:
                return None
            if (
                self._hooks.emit_edge(
                    EdgeDraft(
                        trace_id=identity.trace_id,
                        from_event_id=episode.admission_started.event_id,
                        to_event_id=emitted.record_id,
                        edge_kind="program_order",
                        evidence_source="instrumented_execution_context",
                    )
                )
                is None
            ):
                return None
            result = BaseEventRef(emitted.record_id, timestamp_ns)
            episode.resumed = result
            return result

    def emit_first_compute(
        self,
        runtime_request_id: str,
        recovery_epoch: int,
        *,
        timestamp_ns: int,
        compute_kind: str,
    ) -> BaseEventRef | None:
        """Emit the engine-owned base phase start referenced by the worker."""

        with self._lock:
            identity = self._identities.get(runtime_request_id)
            episode = self._episodes.get((runtime_request_id, recovery_epoch))
            if (
                identity is None
                or episode is None
                or episode.resumed is None
                or episode.first_compute is not None
                or compute_kind not in {"prefill", "decode"}
            ):
                return None
            span_id = self._hooks.new_span_id()
            if span_id is None:
                return None
            emitted = self._hooks.emit_event(
                EventDraft(
                    trace_id=identity.trace_id,
                    lifecycle_id=identity.engine_lifecycle_id,
                    parent_lifecycle_id=f"{identity.trace_id}:r",
                    scope="engine_sample",
                    component="engine_core",
                    event_name=f"{compute_kind}_started",
                    timestamp_ns=timestamp_ns,
                    preemption_epoch=recovery_epoch,
                    start_span_id=span_id,
                    sample_index=identity.sample_index,
                )
            )
            if emitted is None:
                return None
            if (
                self._hooks.emit_edge(
                    EdgeDraft(
                        trace_id=identity.trace_id,
                        from_event_id=episode.resumed.event_id,
                        to_event_id=emitted.record_id,
                        edge_kind="program_order",
                        evidence_source="instrumented_execution_context",
                    )
                )
                is None
            ):
                return None
            result = BaseEventRef(emitted.record_id, timestamp_ns)
            episode.first_compute = result
            return result

    def preempted_event(
        self, runtime_request_id: str, recovery_epoch: int
    ) -> BaseEventRef | None:
        with self._lock:
            episode = self._episodes.get((runtime_request_id, recovery_epoch))
            return episode.preempted if episode is not None else None

    def admission_started_event(
        self, runtime_request_id: str, recovery_epoch: int
    ) -> BaseEventRef | None:
        with self._lock:
            episode = self._episodes.get((runtime_request_id, recovery_epoch))
            return episode.admission_started if episode is not None else None

    def resumed_event(
        self, runtime_request_id: str, recovery_epoch: int
    ) -> BaseEventRef | None:
        with self._lock:
            episode = self._episodes.get((runtime_request_id, recovery_epoch))
            return episode.resumed if episode is not None else None

    def first_compute_event(
        self, runtime_request_id: str, recovery_epoch: int
    ) -> BaseEventRef | None:
        with self._lock:
            episode = self._episodes.get((runtime_request_id, recovery_epoch))
            return episode.first_compute if episode is not None else None

    def request_terminal(self, runtime_request_id: str) -> None:
        with self._lock:
            self._identities.pop(runtime_request_id, None)
            for key in tuple(self._episodes):
                if key[0] == runtime_request_id:
                    self._episodes.pop(key, None)


@dataclass(frozen=True)
class KVRecoveryRuntimeABI:
    """Late-bound constructors from ``vllm.v1.kv_recovery_profile``."""

    binding: Any
    identity_type: Callable[..., Any]
    logical_block_type: Callable[..., Any]
    transfer_context_type: Callable[..., Any]
    compute_context_type: Callable[..., Any]
    receipt_type: Callable[..., Any]
    bounded_worker_observer_type: Callable[..., Any]
    canonical_block_set_id: Callable[[Any, Any, tuple[Any, ...]], str]

    @classmethod
    def load(cls) -> KVRecoveryRuntimeABI:
        """Import the runtime ABI only when an explicit caller requests it."""

        from vllm.v1 import kv_recovery_profile as runtime

        return cls(
            binding=runtime.KV_RECOVERY_PROFILE_BINDING,
            identity_type=runtime.KVRecoveryIdentity,
            logical_block_type=runtime.KVRecoveryLogicalBlock,
            transfer_context_type=runtime.KVRecoveryTransferContext,
            compute_context_type=runtime.KVRecoveryComputeContext,
            receipt_type=runtime.KVRecoveryH2DReceipt,
            bounded_worker_observer_type=runtime.BoundedKVRecoveryWorkerObserver,
            canonical_block_set_id=runtime.canonical_block_set_id,
        )


class BoundedKVRecoveryProfileLedger:
    """Thread-safe producer ledger for the future paired profile exporter.

    This adapter owns deterministic profile ``record_seq`` allocation and the
    four-category loss equations.  It deliberately performs no file I/O; a
    later paired writer may drain its immutable snapshots without changing
    producer ordering.
    """

    def __init__(
        self,
        process_uuid: str,
        *,
        capacity: int = MAX_PROFILE_DATA_RECORDS,
        hooks: RuntimeLifecycleHooks | None = None,
    ):
        self.process_uuid = _require_hex32(process_uuid, "process_uuid")
        if not isinstance(capacity, int) or isinstance(capacity, bool) or capacity < 1:
            raise ValueError("capacity must be a positive integer")
        self.capacity = capacity
        self._hooks = hooks
        self._lock = threading.Lock()
        self._next_record_seq = 0
        self._records: list[ProfileRecord] = []
        self._losses: list[ProfileLossInterval] = []

    @property
    def evidence_complete(self) -> bool:
        if self._hooks is not None:
            return self._hooks.kv_recovery_profile_evidence_complete
        with self._lock:
            return not self._losses

    @property
    def attempted_data_count(self) -> int:
        if self._hooks is not None:
            return self._hooks.kv_recovery_profile_attempted_data_count
        with self._lock:
            return self._next_record_seq

    def write(
        self,
        record_type: ProfileRecordType,
        timestamp_ns: int,
        **fields: object,
    ) -> str | None:
        """Allocate and append one bounded profile data record."""

        if record_type not in {
            "block_set_chunk",
            "wait_set_chunk",
            "transfer_event",
            "recovery_event",
        }:
            raise ValueError("record_type is not in the recovery profile roster")
        if self._hooks is not None:
            reference = self._hooks.emit_kv_recovery_profile(
                record_type, timestamp_ns, **fields
            )
            return reference.record_id if reference is not None else None
        with self._lock:
            record_seq = self._allocate_locked()
            if not _is_uint64(timestamp_ns):
                self._drop_locked(record_type, record_seq, 0, "serialization_failure")
                return None
            if len(self._records) >= self.capacity:
                self._drop_locked(
                    record_type, record_seq, timestamp_ns, "queue_overflow"
                )
                return None
            record_id = f"{self.process_uuid}:k:{record_seq}"
            self._records.append(
                ProfileRecord(
                    record_type=record_type,
                    record_seq=record_seq,
                    record_id=record_id,
                    timestamp_ns=timestamp_ns,
                    fields=dict(fields),
                )
            )
            return record_id

    def drop(
        self,
        record_type: ProfileRecordType,
        timestamp_ns: int | None,
        reason: LossReason = "serialization_failure",
    ) -> int:
        """Consume one exact attempted sequence and extend a maximal loss."""

        if self._hooks is not None:
            record_seq = self._hooks.drop_kv_recovery_profile(
                record_type, timestamp_ns, reason
            )
            return record_seq if record_seq is not None else -1
        with self._lock:
            record_seq = self._allocate_locked()
            observed = timestamp_ns if _is_uint64(timestamp_ns) else 0
            self._drop_locked(record_type, record_seq, observed, reason)
            return record_seq

    def snapshot(
        self,
    ) -> tuple[tuple[ProfileRecord, ...], tuple[ProfileLossInterval, ...]]:
        if self._hooks is not None:
            return self._hooks.kv_recovery_profile_snapshot()
        with self._lock:
            return tuple(self._records), tuple(self._losses)

    def _allocate_locked(self) -> int:
        if self._next_record_seq > _UINT64_MAX:
            raise OverflowError("profile record sequence exhausted")
        value = self._next_record_seq
        self._next_record_seq += 1
        return value

    def _drop_locked(
        self,
        record_type: ProfileRecordType,
        record_seq: int,
        timestamp_ns: int,
        reason: LossReason,
    ) -> None:
        counts = {
            "block_set_chunk": 0,
            "wait_set_chunk": 0,
            "transfer_event": 0,
            "recovery_event": 0,
        }
        counts[record_type] = 1
        if (
            self._losses
            and self._losses[-1].reason == reason
            and self._losses[-1].last_record_seq + 1 == record_seq
        ):
            previous = self._losses[-1]
            merged_counts = dict(previous.counts)
            merged_counts[record_type] += 1
            self._losses[-1] = ProfileLossInterval(
                reason=reason,
                first_record_seq=previous.first_record_seq,
                last_record_seq=record_seq,
                counts=merged_counts,
                first_timestamp_ns=previous.first_timestamp_ns,
                last_timestamp_ns=timestamp_ns,
            )
        else:
            self._losses.append(
                ProfileLossInterval(
                    reason=reason,
                    first_record_seq=record_seq,
                    last_record_seq=record_seq,
                    counts=counts,
                    first_timestamp_ns=timestamp_ns,
                    last_timestamp_ns=timestamp_ns,
                )
            )


@dataclass(frozen=True)
class _WorkerPending:
    attempt: Any
    submit_timestamp_ns: int
    start_event_id: str | None
    span_id: str | None
    restore_start_profile_record_id: str | None


class KVRecoveryWorkerEvidenceAdapter:
    """Worker sink implementing profile rows and H2D base edges 1 and 2."""

    def __init__(
        self,
        hooks: RuntimeLifecycleHooks,
        profile: BoundedKVRecoveryProfileLedger,
        abi: KVRecoveryRuntimeABI,
        run_id: str,
    ) -> None:
        self._hooks = hooks
        self._profile = profile
        self._abi = abi
        self._run_id = _require_hex32(run_id, "run_id")
        self._pending: dict[str, _WorkerPending] = {}
        self._closed = False

    def transfer_submitted(self, attempt: Any, timestamp_ns: int) -> None:
        if self._closed:
            return
        context = attempt.context
        start_event_id: str | None = None
        span_id: str | None = None
        restore_start_profile_record_id: str | None = None
        if context.operation == "h2d_restore":
            span_id = self._hooks.new_span_id()
            if span_id is not None:
                ref = self._hooks.emit_event(
                    EventDraft(
                        trace_id=context.identity.trace_id,
                        lifecycle_id=context.identity.engine_lifecycle_id,
                        parent_lifecycle_id=f"{context.identity.trace_id}:r",
                        scope="engine_sample",
                        component="external_evidence",
                        event_name="communication_started",
                        timestamp_ns=timestamp_ns,
                        preemption_epoch=context.identity.recovery_epoch,
                        start_span_id=span_id,
                        sample_index=0,
                        metadata=self._communication_metadata(attempt),
                    )
                )
                start_event_id = ref.record_id if ref is not None else None
            if (
                start_event_id is None
                or context.identity.base_preempted_event_id is None
            ):
                self._profile.drop("recovery_event", timestamp_ns)
                return
            edge = self._hooks.emit_edge(
                EdgeDraft(
                    trace_id=context.identity.trace_id,
                    from_event_id=context.identity.base_preempted_event_id,
                    to_event_id=start_event_id,
                    edge_kind="data_dependency",
                    evidence_source=KV_RECOVERY_H2D_EVIDENCE,
                )
            )
            if edge is None:
                self._profile.drop("recovery_event", timestamp_ns)
                return
        transfer_record_id = self._profile.write(
            "transfer_event",
            timestamp_ns,
            **self._request_fields(context.identity),
            transfer_id=attempt.transfer_id,
            connector_job_id=attempt.connector_job_id,
            rank=0,
            world_size=1,
            operation=context.operation,
            direction="h2d" if context.operation == "h2d_restore" else "d2h",
            src_medium=(
                "host_cpu" if context.operation == "h2d_restore" else "device_hbm"
            ),
            dst_medium=(
                "device_hbm" if context.operation == "h2d_restore" else "host_cpu"
            ),
            block_set_id=context.block_set_id,
            transfer_phase="submit",
            bytes_moved=None,
            device_duration_ns=None,
            success=None,
            failure_code=None,
        )
        if transfer_record_id is None:
            return
        if context.operation == "h2d_restore":
            restore_start_profile_record_id = self._profile.write(
                "recovery_event",
                timestamp_ns,
                **self._request_fields(context.identity),
                stage="restore_start",
                occurrence=0,
                base_event_id=start_event_id,
                base_admission_started_event_id=None,
                from_profile_event_id=context.identity.preempt_profile_record_id,
                transfer_id=attempt.transfer_id,
                block_set_id=context.block_set_id,
                bytes_moved=None,
                requeue_reason=None,
                compute_kind=None,
                child_observation_kind=None,
                base_association_kind=None,
                base_association_evidence=None,
                request_status_before=None,
                request_status_after=None,
            )
            if restore_start_profile_record_id is None:
                return
        self._pending[attempt.transfer_id] = _WorkerPending(
            attempt=attempt,
            submit_timestamp_ns=timestamp_ns,
            start_event_id=start_event_id,
            span_id=span_id,
            restore_start_profile_record_id=restore_start_profile_record_id,
        )

    def transfer_not_submitted(self, attempt: Any) -> None:
        if not self._closed:
            self._profile.drop("transfer_event", None)

    def transfer_completed(
        self,
        attempt: Any,
        submit_timestamp_ns: int,
        timestamp_ns: int,
        success: bool,
        bytes_moved: int | None,
        device_duration_ns: int | None,
    ) -> Any | None:
        if self._closed:
            return None
        pending = self._pending.pop(attempt.transfer_id, None)
        if (
            pending is None
            or pending.attempt != attempt
            or pending.submit_timestamp_ns != submit_timestamp_ns
            or not success
            or bytes_moved is None
            or bytes_moved <= 0
            or timestamp_ns <= submit_timestamp_ns
        ):
            self._profile.drop("transfer_event", timestamp_ns)
            return None
        context = attempt.context
        done_event_id: str | None = None
        if context.operation == "h2d_restore":
            if pending.span_id is None or pending.start_event_id is None:
                self._profile.drop("recovery_event", timestamp_ns)
                return None
            metadata = dict(self._communication_metadata(attempt))
            metadata["bytes_moved"] = bytes_moved
            done_ref = self._hooks.emit_event(
                EventDraft(
                    trace_id=context.identity.trace_id,
                    lifecycle_id=context.identity.engine_lifecycle_id,
                    parent_lifecycle_id=f"{context.identity.trace_id}:r",
                    scope="engine_sample",
                    component="external_evidence",
                    event_name="communication_done",
                    timestamp_ns=timestamp_ns,
                    preemption_epoch=context.identity.recovery_epoch,
                    end_span_id=pending.span_id,
                    sample_index=0,
                    metadata=metadata,
                )
            )
            done_event_id = done_ref.record_id if done_ref is not None else None
            if done_event_id is None:
                self._profile.drop("recovery_event", timestamp_ns)
                return None
            edge = self._hooks.emit_edge(
                EdgeDraft(
                    trace_id=context.identity.trace_id,
                    from_event_id=pending.start_event_id,
                    to_event_id=done_event_id,
                    edge_kind="program_order",
                    evidence_source="instrumented_execution_context",
                )
            )
            if edge is None:
                self._profile.drop("recovery_event", timestamp_ns)
                return None
        transfer_record_id = self._profile.write(
            "transfer_event",
            timestamp_ns,
            **self._request_fields(context.identity),
            transfer_id=attempt.transfer_id,
            connector_job_id=attempt.connector_job_id,
            rank=0,
            world_size=1,
            operation=context.operation,
            direction="h2d" if context.operation == "h2d_restore" else "d2h",
            src_medium=(
                "host_cpu" if context.operation == "h2d_restore" else "device_hbm"
            ),
            dst_medium=(
                "device_hbm" if context.operation == "h2d_restore" else "host_cpu"
            ),
            block_set_id=context.block_set_id,
            transfer_phase="done",
            bytes_moved=bytes_moved,
            device_duration_ns=device_duration_ns,
            success=True,
            failure_code=None,
        )
        if transfer_record_id is None or context.operation == "d2h_preserve":
            return None
        restore_done_id = self._profile.write(
            "recovery_event",
            timestamp_ns,
            **self._request_fields(context.identity),
            stage="restore_done",
            occurrence=0,
            base_event_id=done_event_id,
            base_admission_started_event_id=None,
            from_profile_event_id=pending.restore_start_profile_record_id,
            transfer_id=attempt.transfer_id,
            block_set_id=context.block_set_id,
            bytes_moved=bytes_moved,
            requeue_reason=None,
            compute_kind=None,
            child_observation_kind=None,
            base_association_kind=None,
            base_association_evidence=None,
            request_status_before=None,
            request_status_after=None,
        )
        process_uuid = self._hooks.process_uuid
        clock_domain_id = self._hooks.clock_domain_id
        if (
            restore_done_id is None
            or done_event_id is None
            or process_uuid is None
            or clock_domain_id is None
        ):
            return None
        try:
            return self._abi.receipt_type(
                binding=context.binding,
                connector_job_id=attempt.connector_job_id,
                transfer_id=attempt.transfer_id,
                identity=context.identity,
                block_set_id=context.block_set_id,
                process_uuid=process_uuid,
                rank=0,
                world_size=1,
                clock_domain_id=clock_domain_id,
                communication_done_event_id=done_event_id,
                restore_done_profile_record_id=restore_done_id,
                timestamp_ns=timestamp_ns,
                bytes_moved=bytes_moved,
            )
        except Exception:  # noqa: BLE001 - serving-side evidence is fail-open.
            self._profile.drop("recovery_event", timestamp_ns)
            return None

    def transfer_capacity_exhausted(
        self,
        attempt: Any,
        capacity: str,
        timestamp_ns: int | None,
        loss_reason: LossReason,
    ) -> None:
        del attempt, capacity
        self._profile.drop("transfer_event", timestamp_ns, loss_reason)

    def evidence_failure(
        self,
        reason: str,
        connector_job_ids: tuple[int, ...],
        transfer_ids: tuple[str, ...],
        timestamp_ns: int | None,
    ) -> None:
        del reason, connector_job_ids, transfer_ids
        self._profile.drop("transfer_event", timestamp_ns)

    def wait_completed(self, attempt: Any) -> None:
        if self._closed:
            return
        process_uuid = self._hooks.process_uuid
        if process_uuid is None:
            self._profile.drop("wait_set_chunk", attempt.entry_timestamp_ns)
            return
        transfer_ids = tuple(attempt.transfer_ids)
        raw = (
            f"{PROFILE_ID}\0{self._run_id}\0{process_uuid}\0"
            + "".join(f"{transfer_id}\n" for transfer_id in transfer_ids)
        ).encode("ascii")
        wait_set_id = hashlib.sha256(raw).hexdigest()
        chunk_count = (len(transfer_ids) + 63) // 64
        for chunk_index in range(chunk_count):
            chunk = transfer_ids[chunk_index * 64 : (chunk_index + 1) * 64]
            if (
                self._profile.write(
                    "wait_set_chunk",
                    attempt.entry_timestamp_ns,
                    operation="transfer_wait",
                    wait_set_id=wait_set_id,
                    chunk_index=chunk_index,
                    chunk_count=chunk_count,
                    total_transfer_count=len(transfer_ids),
                    transfer_ids=chunk,
                )
                is None
            ):
                return

    def h2d_receipt_capacity_exhausted(
        self, receipt: Any, loss_reason: LossReason
    ) -> None:
        self._profile.drop("recovery_event", receipt.timestamp_ns, loss_reason)

    def first_compute(
        self,
        context: Any,
        timestamp_ns: int,
        compute_kind: str,
        base_event_id: str,
    ) -> None:
        """Write the worker child observation with its scheduler predecessor."""

        try:
            if (
                context.binding != self._abi.binding
                or context.identity.recovery_epoch is None
                or compute_kind not in {"prefill", "decode"}
            ):
                raise ValueError("invalid first-compute sidecar")
            _require_event_id(base_event_id, "base_event_id")
            identity = context.identity
            self._profile.write(
                "recovery_event",
                timestamp_ns,
                **self._request_fields(identity),
                stage="first_prefill_or_decode",
                occurrence=0,
                base_event_id=base_event_id,
                base_admission_started_event_id=None,
                from_profile_event_id=context.admission_profile_record_id,
                transfer_id=context.transfer_id,
                block_set_id=context.block_set_id,
                bytes_moved=context.bytes_moved,
                requeue_reason=None,
                compute_kind=compute_kind,
                child_observation_kind="worker_model_forward_entry",
                base_association_kind="phase_child_observation",
                base_association_evidence="instrumented_execution_context",
                request_status_before="RUNNING",
                request_status_after="RUNNING",
            )
        except Exception:  # noqa: BLE001 - serving remains fail-open.
            self._profile.drop(
                "recovery_event",
                timestamp_ns if _is_uint64(timestamp_ns) else None,
            )

    def close(self, open_attempts: tuple[Any, ...], evidence_disabled: bool) -> None:
        if self._closed:
            return
        self._closed = True
        for _attempt in open_attempts:
            self._profile.drop("transfer_event", None)
        if evidence_disabled and self._profile.evidence_complete:
            self._profile.drop("recovery_event", None)
        self._pending.clear()

    @staticmethod
    def _communication_metadata(attempt: Any) -> dict[str, object]:
        context = attempt.context
        return {
            "operation": "h2d_restore",
            "direction": "h2d",
            "transfer_id": attempt.transfer_id,
            "block_set_id": context.block_set_id,
            "recovery_profile": PROFILE_ID,
            "recovery_profile_sha256": PROFILE_SHA256,
            "communication_mapping": KV_RECOVERY_COMMUNICATION_MODE,
            "communication_mapping_sha256": MAPPING_SHA256,
            "rank": 0,
        }

    @staticmethod
    def _request_fields(identity: Any) -> dict[str, object]:
        return {
            "trace_id": identity.trace_id,
            "engine_lifecycle_id": identity.engine_lifecycle_id,
            "runtime_request_id": identity.runtime_request_id,
            "request_id_kind": "engine_internal",
            "sample_index": 0,
            "recovery_epoch": identity.recovery_epoch,
            "episode_id": identity.episode_id,
        }


@dataclass
class _SchedulerEpisode:
    identity: RequestLifecycleIdentity
    recovery_epoch: int
    preempted_event: BaseEventRef
    preempt_profile_record_id: str
    context: Any | None = None
    receipt: Any | None = None
    admission_started_event: BaseEventRef | None = None
    wakeup_profile_record_id: str | None = None
    predecessor_profile_record_id: str | None = None
    requeue_occurrence: int = 0
    admission_profile_record_id: str | None = None


class KVRecoverySchedulerAdapter:
    """EngineCore adapter owning exact identities and H2D return edge 3."""

    def __init__(
        self,
        run_id: str,
        hooks: RuntimeLifecycleHooks,
        profile: BoundedKVRecoveryProfileLedger,
        bridge: BaseLifecycleBridge,
        abi: KVRecoveryRuntimeABI,
        *,
        clock_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self._run_id = _require_hex32(run_id, "run_id")
        self._hooks = hooks
        self._profile = profile
        self._bridge = bridge
        self._abi = abi
        self._clock_ns = clock_ns
        self._episodes: dict[str, _SchedulerEpisode] = {}
        self._logical_ids: dict[tuple[str, int, int], str] = {}
        self._closed = False

    def request_preempted(
        self, runtime_request_id: str, recovery_epoch: int
    ) -> str | None:
        if self._closed or recovery_epoch < 1:
            return None
        identity = self._bridge.request_identity(runtime_request_id)
        base_event = self._bridge.preempted_event(runtime_request_id, recovery_epoch)
        if identity is None or base_event is None:
            self._profile.drop("recovery_event", None)
            self._episodes.pop(runtime_request_id, None)
            return None
        if runtime_request_id in self._episodes:
            self._profile.drop("recovery_event", None)
        profile_id = self._profile.write(
            "recovery_event",
            base_event.timestamp_ns,
            trace_id=identity.trace_id,
            engine_lifecycle_id=identity.engine_lifecycle_id,
            runtime_request_id=identity.runtime_request_id,
            request_id_kind="engine_internal",
            sample_index=0,
            recovery_epoch=recovery_epoch,
            episode_id=f"{identity.engine_lifecycle_id}:k:{recovery_epoch}",
            stage="preempt",
            occurrence=0,
            base_event_id=base_event.event_id,
            base_admission_started_event_id=None,
            from_profile_event_id=None,
            transfer_id=None,
            block_set_id=None,
            bytes_moved=None,
            requeue_reason=None,
            compute_kind=None,
            child_observation_kind=None,
            base_association_kind=None,
            base_association_evidence=None,
            request_status_before="RUNNING",
            request_status_after="PREEMPTED",
        )
        if profile_id is None:
            self._episodes.pop(runtime_request_id, None)
            return None
        self._episodes[runtime_request_id] = _SchedulerEpisode(
            identity=identity,
            recovery_epoch=recovery_epoch,
            preempted_event=base_event,
            preempt_profile_record_id=profile_id,
        )
        return profile_id

    def prepare_transfer_context(
        self,
        runtime_request_id: str,
        operation: str,
        coordinates: tuple[Any, ...],
    ) -> Any | None:
        if self._closed or not coordinates:
            return None
        base_identity = self._bridge.request_identity(runtime_request_id)
        if base_identity is None:
            self._profile.drop("block_set_chunk", None)
            return None
        episode = self._episodes.get(runtime_request_id)
        if operation == "h2d_restore":
            if episode is None:
                self._profile.drop("block_set_chunk", None)
                return None
            recovery_epoch: int | None = episode.recovery_epoch
            episode_id: str | None = (
                f"{base_identity.engine_lifecycle_id}:k:{recovery_epoch}"
            )
            preempted_event_id: str | None = episode.preempted_event.event_id
        elif operation == "d2h_preserve":
            recovery_epoch = None
            episode_id = None
            preempted_event_id = None
        else:
            self._profile.drop("block_set_chunk", None)
            return None
        try:
            identity = self._abi.identity_type(
                run_id=self._run_id,
                trace_id=base_identity.trace_id,
                engine_lifecycle_id=base_identity.engine_lifecycle_id,
                runtime_request_id=runtime_request_id,
                recovery_epoch=recovery_epoch,
                episode_id=episode_id,
                base_preempted_event_id=preempted_event_id,
                preempt_profile_record_id=(
                    episode.preempt_profile_record_id
                    if operation == "h2d_restore" and episode is not None
                    else None
                ),
            )
            logical_blocks = tuple(
                self._abi.logical_block_type(
                    group_index=coordinate.group_index,
                    logical_ordinal=coordinate.logical_ordinal,
                    logical_block_id=self._logical_block_id(
                        base_identity,
                        coordinate.group_index,
                        coordinate.logical_ordinal,
                    ),
                )
                for coordinate in coordinates
            )
            block_set_id = self._abi.canonical_block_set_id(
                self._abi.binding, identity, logical_blocks
            )
            context = self._abi.transfer_context_type(
                binding=self._abi.binding,
                identity=identity,
                operation=operation,
                block_set_id=block_set_id,
                logical_blocks=logical_blocks,
            )
        except Exception:  # noqa: BLE001 - serving-side evidence is fail-open.
            self._profile.drop("block_set_chunk", None)
            return None
        try:
            timestamp_ns = self._clock_ns()
        except Exception:  # noqa: BLE001 - serving-side evidence is fail-open.
            self._profile.drop("block_set_chunk", None)
            return None
        chunk_count = (len(logical_blocks) + 63) // 64
        for chunk_index in range(chunk_count):
            chunk = logical_blocks[chunk_index * 64 : (chunk_index + 1) * 64]
            block_record = self._profile.write(
                "block_set_chunk",
                timestamp_ns,
                trace_id=base_identity.trace_id,
                engine_lifecycle_id=base_identity.engine_lifecycle_id,
                runtime_request_id=base_identity.runtime_request_id,
                request_id_kind="engine_internal",
                sample_index=0,
                recovery_epoch=recovery_epoch,
                episode_id=episode_id,
                block_set_id=block_set_id,
                chunk_index=chunk_index,
                chunk_count=chunk_count,
                total_block_count=len(logical_blocks),
                blocks=tuple(
                    {
                        "group_index": block.group_index,
                        "logical_ordinal": block.logical_ordinal,
                        "logical_block_id": block.logical_block_id,
                    }
                    for block in chunk
                ),
            )
            if block_record is None:
                return None
        if episode is not None and operation == "h2d_restore":
            episode.context = context
        return context

    def consume_h2d_receipts(
        self, receipts: tuple[Any, ...], receipt_capacity_exhausted: bool
    ) -> None:
        if self._closed:
            return
        if receipt_capacity_exhausted:
            self._profile.drop("recovery_event", None)
        for receipt in receipts:
            runtime_request_id = receipt.identity.runtime_request_id
            episode = self._episodes.get(runtime_request_id)
            if (
                episode is None
                or episode.context is None
                or episode.receipt is not None
                or receipt.binding != self._abi.binding
                or receipt.identity != episode.context.identity
                or receipt.block_set_id != episode.context.block_set_id
                or receipt.identity.recovery_epoch != episode.recovery_epoch
            ):
                self._profile.drop("recovery_event", receipt.timestamp_ns)
                continue
            episode.receipt = receipt

    def request_admission_started(
        self, runtime_request_id: str, recovery_epoch: int
    ) -> None:
        episode = self._episodes.get(runtime_request_id)
        if (
            self._closed
            or episode is None
            or episode.receipt is None
            or recovery_epoch != episode.recovery_epoch
            or episode.admission_started_event is not None
        ):
            return
        wakeup_timestamp_ns = self._clock_ns()
        event = self._bridge.admission_started_event(runtime_request_id, recovery_epoch)
        if event is None or not _is_uint64(wakeup_timestamp_ns):
            self._profile.drop("recovery_event", episode.receipt.timestamp_ns)
            return
        if wakeup_timestamp_ns > event.timestamp_ns:
            self._profile.drop("recovery_event", episode.receipt.timestamp_ns)
            return
        profile_id = self._profile.write(
            "recovery_event",
            wakeup_timestamp_ns,
            trace_id=episode.identity.trace_id,
            engine_lifecycle_id=episode.identity.engine_lifecycle_id,
            runtime_request_id=episode.identity.runtime_request_id,
            request_id_kind="engine_internal",
            sample_index=0,
            recovery_epoch=recovery_epoch,
            episode_id=f"{episode.identity.engine_lifecycle_id}:k:{recovery_epoch}",
            stage="scheduler_wakeup",
            occurrence=0,
            base_event_id=None,
            base_admission_started_event_id=None,
            from_profile_event_id=episode.receipt.restore_done_profile_record_id,
            transfer_id=episode.receipt.transfer_id,
            block_set_id=episode.receipt.block_set_id,
            bytes_moved=episode.receipt.bytes_moved,
            requeue_reason=None,
            compute_kind=None,
            child_observation_kind=None,
            base_association_kind=None,
            base_association_evidence=None,
            request_status_before="WAITING_FOR_REMOTE_KVS",
            request_status_after="PREEMPTED",
        )
        if profile_id is not None:
            episode.admission_started_event = event
            episode.wakeup_profile_record_id = profile_id
            episode.predecessor_profile_record_id = profile_id

    def request_requeued(
        self,
        runtime_request_id: str,
        recovery_epoch: int,
        reason: str,
    ) -> None:
        episode = self._episodes.get(runtime_request_id)
        if (
            self._closed
            or episode is None
            or episode.receipt is None
            or episode.wakeup_profile_record_id is None
            or episode.predecessor_profile_record_id is None
            or episode.admission_profile_record_id is not None
            or recovery_epoch != episode.recovery_epoch
        ):
            return
        try:
            timestamp_ns = self._clock_ns()
        except Exception:  # noqa: BLE001 - serving-side evidence is fail-open.
            self._profile.drop("recovery_event", None)
            return
        profile_id = self._profile.write(
            "recovery_event",
            timestamp_ns,
            trace_id=episode.identity.trace_id,
            engine_lifecycle_id=episode.identity.engine_lifecycle_id,
            runtime_request_id=episode.identity.runtime_request_id,
            request_id_kind="engine_internal",
            sample_index=0,
            recovery_epoch=recovery_epoch,
            episode_id=f"{episode.identity.engine_lifecycle_id}:k:{recovery_epoch}",
            stage="requeue",
            occurrence=episode.requeue_occurrence,
            base_event_id=None,
            base_admission_started_event_id=None,
            from_profile_event_id=episode.predecessor_profile_record_id,
            transfer_id=episode.receipt.transfer_id,
            block_set_id=episode.receipt.block_set_id,
            bytes_moved=episode.receipt.bytes_moved,
            requeue_reason=reason,
            compute_kind=None,
            child_observation_kind=None,
            base_association_kind=None,
            base_association_evidence=None,
            request_status_before="PREEMPTED",
            request_status_after="PREEMPTED",
        )
        if profile_id is not None:
            episode.predecessor_profile_record_id = profile_id
            episode.requeue_occurrence += 1

    def request_admitted(
        self, runtime_request_id: str, recovery_epoch: int
    ) -> Any | None:
        episode = self._episodes.get(runtime_request_id)
        if (
            self._closed
            or episode is None
            or episode.receipt is None
            or episode.admission_started_event is None
            or episode.wakeup_profile_record_id is None
            or episode.predecessor_profile_record_id is None
            or episode.admission_profile_record_id is not None
            or recovery_epoch != episode.recovery_epoch
        ):
            return None
        resumed_event = self._bridge.resumed_event(runtime_request_id, recovery_epoch)
        if resumed_event is None:
            self._profile.drop("recovery_event", episode.receipt.timestamp_ns)
            return None
        if resumed_event.timestamp_ns < episode.admission_started_event.timestamp_ns:
            self._profile.drop("recovery_event", episode.receipt.timestamp_ns)
            return None
        edge = self._hooks.emit_edge(
            EdgeDraft(
                trace_id=episode.identity.trace_id,
                from_event_id=episode.receipt.communication_done_event_id,
                to_event_id=episode.admission_started_event.event_id,
                edge_kind="data_dependency",
                evidence_source=KV_RECOVERY_H2D_EVIDENCE,
            )
        )
        if edge is None:
            self._profile.drop("recovery_event", episode.receipt.timestamp_ns)
            return None
        profile_id = self._profile.write(
            "recovery_event",
            resumed_event.timestamp_ns,
            trace_id=episode.identity.trace_id,
            engine_lifecycle_id=episode.identity.engine_lifecycle_id,
            runtime_request_id=episode.identity.runtime_request_id,
            request_id_kind="engine_internal",
            sample_index=0,
            recovery_epoch=recovery_epoch,
            episode_id=f"{episode.identity.engine_lifecycle_id}:k:{recovery_epoch}",
            stage="admission",
            occurrence=0,
            base_event_id=resumed_event.event_id,
            base_admission_started_event_id=(episode.admission_started_event.event_id),
            from_profile_event_id=episode.predecessor_profile_record_id,
            transfer_id=episode.receipt.transfer_id,
            block_set_id=episode.receipt.block_set_id,
            bytes_moved=episode.receipt.bytes_moved,
            requeue_reason=None,
            compute_kind=None,
            child_observation_kind=None,
            base_association_kind=None,
            base_association_evidence=None,
            request_status_before="PREEMPTED",
            request_status_after="RUNNING",
        )
        if profile_id is None:
            return None
        episode.admission_profile_record_id = profile_id
        try:
            context = self._abi.compute_context_type(
                binding=self._abi.binding,
                identity=episode.receipt.identity,
                transfer_id=episode.receipt.transfer_id,
                block_set_id=episode.receipt.block_set_id,
                bytes_moved=episode.receipt.bytes_moved,
                admission_profile_record_id=profile_id,
            )
        except Exception:  # noqa: BLE001 - serving-side evidence is fail-open.
            self._profile.drop("recovery_event", resumed_event.timestamp_ns)
            return None
        self._episodes.pop(runtime_request_id, None)
        return context

    def request_terminal(self, runtime_request_id: str) -> None:
        episode = self._episodes.pop(runtime_request_id, None)
        if episode is not None:
            self._profile.drop("recovery_event", None)

    def reset(self, stale_job_threshold: int) -> None:
        del stale_job_threshold
        for _episode in self._episodes.values():
            self._profile.drop("recovery_event", None)
        self._episodes.clear()

    def close(self) -> None:
        if self._closed:
            return
        self.reset(0)
        self._closed = True
        self._logical_ids.clear()

    def _logical_block_id(
        self,
        identity: RequestLifecycleIdentity,
        group_index: int,
        logical_ordinal: int,
    ) -> str:
        key = (identity.engine_lifecycle_id, group_index, logical_ordinal)
        value = self._logical_ids.get(key)
        if value is None:
            raw = (
                f"{self._run_id}\0{identity.engine_lifecycle_id}\0"
                f"{group_index}:{logical_ordinal}"
            ).encode("ascii")
            value = hashlib.sha256(raw).hexdigest()[:32]
            self._logical_ids[key] = value
        return value


class KVRecoveryObserverFactoryAdapter:
    """Late-bound vLLM observer factory with a closed default-off gate."""

    def __init__(
        self,
        run_id: str,
        hooks: RuntimeLifecycleHooks,
        bridge: BaseLifecycleBridge,
        abi: KVRecoveryRuntimeABI,
        *,
        clock_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self._run_id = _require_hex32(run_id, "run_id")
        self._hooks = hooks
        self._bridge = bridge
        self._abi = abi
        self._clock_ns = clock_ns
        self._lock = threading.Lock()
        self._profiles: dict[str, BoundedKVRecoveryProfileLedger] = {}

    @property
    def profile_ledgers(self) -> tuple[BoundedKVRecoveryProfileLedger, ...]:
        with self._lock:
            return tuple(self._profiles.values())

    def reinitialize_after_fork(self, binding: Any) -> None:
        if binding != self._abi.binding:
            raise ValueError("runtime binding differs from the adapter ABI")
        if not self._hooks.reinitialize_after_fork():
            raise RuntimeError("trace exporter could not reinitialize after fork")

    def create_scheduler_observer(self, binding: Any) -> Any | None:
        if not self._source_conformance_gate_open(binding):
            return None
        profile = self._profile_for_current_process()
        if profile is None:
            return None
        return KVRecoverySchedulerAdapter(
            self._run_id,
            self._hooks,
            profile,
            self._bridge,
            self._abi,
            clock_ns=self._clock_ns,
        )

    def create_worker_observer(self, binding: Any) -> Any | None:
        if not self._source_conformance_gate_open(binding):
            return None
        process_uuid = self._hooks.process_uuid
        clock_domain_id = self._hooks.clock_domain_id
        profile = self._profile_for_current_process()
        if process_uuid is None or clock_domain_id is None or profile is None:
            return None
        sink = KVRecoveryWorkerEvidenceAdapter(
            self._hooks, profile, self._abi, self._run_id
        )
        try:
            return self._abi.bounded_worker_observer_type(
                process_uuid,
                self._run_id,
                clock_domain_id,
                sink,
            )
        except Exception:  # noqa: BLE001 - plugin construction is fail-open.
            profile.drop("recovery_event", None)
            return None

    def _source_conformance_gate_open(self, binding: Any) -> bool:
        # Environment-derived RuntimeTraceConfig still rejects this mode.  The
        # comparison only makes explicit source-conformance tests executable;
        # it is not a runtime activation switch.
        return (
            binding == self._abi.binding
            and self._hooks.enabled
            and self._hooks.config.communication_mode == KV_RECOVERY_COMMUNICATION_MODE
            and self._hooks.kv_recovery_profile_enabled
            and self._hooks.config.kv_recovery_profile_config
            == KVRecoveryProfileConfig(run_id=self._run_id)
        )

    def _profile_for_current_process(
        self,
    ) -> BoundedKVRecoveryProfileLedger | None:
        process_uuid = self._hooks.process_uuid
        if process_uuid is None:
            return None
        with self._lock:
            profile = self._profiles.get(process_uuid)
            if profile is None:
                profile = BoundedKVRecoveryProfileLedger(
                    process_uuid, hooks=self._hooks
                )
                self._profiles[process_uuid] = profile
            return profile


@dataclass(frozen=True)
class ExpectedH2DRecovery:
    trace_id: str
    engine_lifecycle_id: str
    recovery_epoch: int
    transfer_id: str
    block_set_id: str
    preempted_event_id: str
    admission_started_event_id: str


@dataclass(frozen=True)
class NormalizedH2DRecovery:
    start_event_id: str
    done_event_id: str
    duration_ns: int
    bytes_moved: int
    edge_ids: tuple[str, str, str]


def normalize_h2d_recovery(
    records: Iterable[Mapping[str, object]],
    expected: ExpectedH2DRecovery,
    *,
    profile_evidence_complete: bool,
) -> NormalizedH2DRecovery:
    """Validate one explicit H2D bridge without selecting or repairing edges."""

    if not profile_evidence_complete:
        raise ValueError("profile evidence contains loss")
    rows = tuple(records)
    if any(row.get("record_type") == "loss_interval" for row in rows):
        raise ValueError("base evidence contains loss")
    events = {
        row.get("event_id"): row
        for row in rows
        if row.get("record_type") == "event" and isinstance(row.get("event_id"), str)
    }
    edges = [row for row in rows if row.get("record_type") == "edge"]
    preempted = events.get(expected.preempted_event_id)
    admission = events.get(expected.admission_started_event_id)
    if preempted is None or preempted.get("event_name") != "preempted":
        raise ValueError("exact preempted endpoint is missing")
    if admission is None or admission.get("event_name") != "admission_started":
        raise ValueError("exact admission_started endpoint is missing")
    if (
        preempted.get("trace_id") != expected.trace_id
        or admission.get("trace_id") != expected.trace_id
        or preempted.get("lifecycle_id") != expected.engine_lifecycle_id
        or admission.get("lifecycle_id") != expected.engine_lifecycle_id
        or preempted.get("preemption_epoch") != expected.recovery_epoch - 1
        or admission.get("preemption_epoch") != expected.recovery_epoch
    ):
        raise ValueError("base recovery endpoint identity drifted")
    communication_rows = [
        row
        for row in events.values()
        if row.get("trace_id") == expected.trace_id
        and row.get("event_name") in {"communication_started", "communication_done"}
    ]
    if any(
        not isinstance(row.get("metadata"), Mapping)
        or row["metadata"].get("operation") != "h2d_restore"
        or row["metadata"].get("transfer_id") != expected.transfer_id
        for row in communication_rows
    ):
        raise ValueError("closed H2D base roster contains another operation")
    candidates = [
        row
        for row in events.values()
        if isinstance(row.get("metadata"), Mapping)
        and row["metadata"].get("transfer_id") == expected.transfer_id
    ]
    starts = [
        row for row in candidates if row.get("event_name") == "communication_started"
    ]
    dones = [row for row in candidates if row.get("event_name") == "communication_done"]
    if len(starts) != 1 or len(dones) != 1:
        raise ValueError("H2D communication pair is missing or duplicated")
    start, done = starts[0], dones[0]
    for row in (start, done):
        metadata = row["metadata"]
        assert isinstance(metadata, Mapping)
        if (
            row.get("trace_id") != expected.trace_id
            or row.get("lifecycle_id") != expected.engine_lifecycle_id
            or row.get("preemption_epoch") != expected.recovery_epoch
            or metadata.get("block_set_id") != expected.block_set_id
            or metadata.get("operation") != "h2d_restore"
            or metadata.get("communication_mapping") != KV_RECOVERY_COMMUNICATION_MODE
        ):
            raise ValueError("H2D communication identity drifted")
    start_id = start["event_id"]
    done_id = done["event_id"]
    if not isinstance(start_id, str) or not isinstance(done_id, str):
        raise TypeError("communication event ID is invalid")
    if start.get("start_span_id") != done.get("end_span_id"):
        raise ValueError("communication span endpoints differ")
    start_ns, done_ns = start.get("timestamp_ns"), done.get("timestamp_ns")
    if not _is_uint64(start_ns) or not _is_uint64(done_ns) or done_ns <= start_ns:
        raise ValueError("communication duration is not strictly positive")
    preempted_ns = preempted.get("timestamp_ns")
    admission_ns = admission.get("timestamp_ns")
    if (
        not _is_uint64(preempted_ns)
        or not _is_uint64(admission_ns)
        or preempted_ns > start_ns
        or done_ns > admission_ns
    ):
        raise ValueError("H2D endpoints are not causally ordered")
    done_metadata = done["metadata"]
    assert isinstance(done_metadata, Mapping)
    bytes_moved = done_metadata.get("bytes_moved")
    if not _is_uint64(bytes_moved) or bytes_moved < 1:
        raise ValueError("communication bytes are not positive")
    expected_edges = (
        (
            expected.preempted_event_id,
            start_id,
            "data_dependency",
            KV_RECOVERY_H2D_EVIDENCE,
        ),
        (
            start_id,
            done_id,
            "program_order",
            "instrumented_execution_context",
        ),
        (
            done_id,
            expected.admission_started_event_id,
            "data_dependency",
            KV_RECOVERY_H2D_EVIDENCE,
        ),
    )
    edge_ids: list[str] = []
    for expected_edge in expected_edges:
        matches = [
            edge
            for edge in edges
            if (
                edge.get("from_event_id"),
                edge.get("to_event_id"),
                edge.get("edge_kind"),
                edge.get("evidence_source"),
            )
            == expected_edge
        ]
        if len(matches) != 1 or not isinstance(matches[0].get("edge_id"), str):
            raise ValueError("required H2D edge is missing or duplicated")
        edge_ids.append(matches[0]["edge_id"])
    relevant_ids = {
        expected.preempted_event_id,
        start_id,
        done_id,
        expected.admission_started_event_id,
    }
    relevant_edges = [
        edge
        for edge in edges
        if edge.get("from_event_id") in relevant_ids
        and edge.get("to_event_id") in relevant_ids
        and (
            edge.get("evidence_source") == KV_RECOVERY_H2D_EVIDENCE
            or (
                edge.get("from_event_id") == start_id
                and edge.get("to_event_id") == done_id
            )
        )
    ]
    if len(relevant_edges) != 3:
        raise ValueError("H2D edge roster contains an extra or duplicate edge")
    mapped_edges = [
        edge
        for edge in edges
        if edge.get("trace_id") == expected.trace_id
        and edge.get("evidence_source") == KV_RECOVERY_H2D_EVIDENCE
    ]
    if len(mapped_edges) != 2:
        raise ValueError("H2D specialty edge roster is not exact")
    return NormalizedH2DRecovery(
        start_event_id=start_id,
        done_event_id=done_id,
        duration_ns=done_ns - start_ns,
        bytes_moved=bytes_moved,
        edge_ids=(edge_ids[0], edge_ids[1], edge_ids[2]),
    )


__all__ = [
    "BaseEventRef",
    "BaseLifecycleBridge",
    "BoundedKVRecoveryProfileLedger",
    "ExpectedH2DRecovery",
    "KVRecoveryObserverFactoryAdapter",
    "KVRecoveryRuntimeABI",
    "KVRecoverySchedulerAdapter",
    "KVRecoveryWorkerEvidenceAdapter",
    "NormalizedH2DRecovery",
    "ProfileLossInterval",
    "ProfileRecord",
    "RequestLifecycleIdentity",
    "RuntimeBaseLifecycleBridge",
    "normalize_h2d_recovery",
]
