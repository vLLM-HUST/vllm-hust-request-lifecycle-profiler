"""Default-off KV-recovery runtime adapters and strict normalization.

The classes in this module are constructed only by explicit callers and
require the runtime ABI plus already-emitted base lifecycle identities.
Serving-facing callbacks are fail-open; invalid profile evidence is dropped.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from vllm_request_lifecycle_profiler.kv_recovery_profile_protocol import (
    MAX_PROFILE_DATA_RECORDS,
    MAX_RUNTIME_REQUEST_ID_BYTES,
    PROFILE_ID,
    KVRecoveryProfileConfig,
    LossReason,
    ProfileLossInterval,
    ProfileRecord,
    ProfileRecordType,
    profile_record_line,
)
from vllm_request_lifecycle_profiler.runtime_hooks import RuntimeLifecycleHooks
from vllm_request_lifecycle_profiler.runtime_protocol import (
    KV_RECOVERY_COMMUNICATION_MODE,
    KV_RECOVERY_H2D_EVIDENCE,
    EdgeDraft,
    EventDraft,
    canonical_json_line,
)

_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_EVENT_ID = re.compile(r"^[0-9a-f]{32}:e:(0|[1-9][0-9]{0,19})$")
_UINT64_MAX = 2**64 - 1

# Each profile record is capped at MAX_PROFILE_RECORD_BYTES (4096). A
# block_set_chunk row is ~75 bytes, so a full 64-row chunk can exceed the
# wire budget once identity/metadata overhead is included. Chunk conservatively
# so a chunked block set always serializes below the cap.
_MAX_BLOCK_ROWS_PER_CHUNK_BYTE_BUDGET = 32

logger = logging.getLogger(__name__)


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


def _is_bounded_printable_ascii(value: object, max_bytes: int) -> bool:
    return (
        isinstance(value, str)
        and value.isascii()
        and value.isprintable()
        and 1 <= len(value) <= max_bytes
    )


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
        if not _is_bounded_printable_ascii(
            self.runtime_request_id, MAX_RUNTIME_REQUEST_ID_BYTES
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

    def register_runtime_request(
        self, run_id: str, runtime_request_id: str, *, timestamp_ns: int
    ) -> bool: ...

    def emit_runtime_scheduled(
        self,
        runtime_request_id: str,
        *,
        timestamp_ns: int,
        compute_kind: str,
        scheduled_tokens: int,
        prompt_tokens_total: int,
        prompt_tokens_cached: int,
    ) -> bool: ...

    def emit_runtime_preempted(
        self, runtime_request_id: str, recovery_epoch: int, *, timestamp_ns: int
    ) -> BaseEventRef | None: ...

    def emit_runtime_admission_started(
        self, runtime_request_id: str, recovery_epoch: int, *, timestamp_ns: int
    ) -> BaseEventRef | None: ...

    def emit_runtime_resumed(
        self,
        runtime_request_id: str,
        recovery_epoch: int,
        *,
        timestamp_ns: int,
        prompt_tokens_total: int,
        prompt_tokens_cached: int,
    ) -> BaseEventRef | None: ...

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

    def emit_first_compute(
        self,
        runtime_request_id: str,
        recovery_epoch: int,
        *,
        timestamp_ns: int,
        compute_kind: str,
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


@dataclass
class _RuntimeRequestState:
    identity: RequestLifecycleIdentity
    queue_started: BaseEventRef
    queue_span_id: str
    active_started: BaseEventRef | None = None
    active_span_id: str | None = None
    prompt_tokens_computed: int = 0
    prefill_chunk_count: int = 0


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
        self._runtime_states: dict[str, _RuntimeRequestState] = {}

    def register_request(self, identity: RequestLifecycleIdentity) -> bool:
        with self._lock:
            current = self._identities.get(identity.runtime_request_id)
            if current is not None:
                return current == identity
            if len(self._identities) >= self._capacity:
                return False
            self._identities[identity.runtime_request_id] = identity
            return True

    def register_runtime_request(
        self,
        run_id: str,
        runtime_request_id: str,
        *,
        timestamp_ns: int,
    ) -> bool:
        """Register a request at the real connector request-entry callback."""

        if not _is_bounded_printable_ascii(
            runtime_request_id, MAX_RUNTIME_REQUEST_ID_BYTES
        ):
            return False
        trace_id = hashlib.sha256(
            f"{run_id}\0{runtime_request_id}".encode("ascii")
        ).hexdigest()[:32]
        identity = RequestLifecycleIdentity(
            trace_id=trace_id,
            engine_lifecycle_id=f"{trace_id}:e:0",
            runtime_request_id=runtime_request_id,
        )
        with self._lock:
            current = self._runtime_states.get(runtime_request_id)
            if current is not None:
                return current.identity == identity
            if len(self._identities) >= self._capacity:
                return False
            queue_span_id = self._hooks.new_span_id()
            if queue_span_id is None:
                return False
            emitted = self._hooks.emit_event(
                EventDraft(
                    trace_id=identity.trace_id,
                    lifecycle_id=identity.engine_lifecycle_id,
                    parent_lifecycle_id=f"{identity.trace_id}:r",
                    scope="engine_sample",
                    component="engine_client",
                    event_name="queued",
                    timestamp_ns=timestamp_ns,
                    preemption_epoch=0,
                    start_span_id=queue_span_id,
                    sample_index=0,
                )
            )
            if emitted is None:
                return False
            queued = BaseEventRef(emitted.record_id, timestamp_ns)
            self._identities[runtime_request_id] = identity
            self._runtime_states[runtime_request_id] = _RuntimeRequestState(
                identity=identity,
                queue_started=queued,
                queue_span_id=queue_span_id,
            )
            return True

    def emit_runtime_scheduled(
        self,
        runtime_request_id: str,
        *,
        timestamp_ns: int,
        compute_kind: str,
        scheduled_tokens: int,
        prompt_tokens_total: int,
        prompt_tokens_cached: int,
    ) -> bool:
        """Capture a committed scheduler step and its active compute span."""

        with self._lock:
            state = self._runtime_states.get(runtime_request_id)
            if (
                state is None
                or compute_kind not in {"prefill", "decode"}
                or scheduled_tokens < 1
                or prompt_tokens_total < 1
            ):
                return False
            prompt_tokens_cached = min(
                max(0, prompt_tokens_cached), prompt_tokens_total - 1
            )
            if state.active_started is not None:
                state.prompt_tokens_computed = min(
                    prompt_tokens_total,
                    state.prompt_tokens_computed + scheduled_tokens,
                )
                if compute_kind == "prefill":
                    state.prefill_chunk_count += 1
                return True
            scheduled = self._hooks.emit_event(
                EventDraft(
                    trace_id=state.identity.trace_id,
                    lifecycle_id=state.identity.engine_lifecycle_id,
                    parent_lifecycle_id=f"{state.identity.trace_id}:r",
                    scope="engine_sample",
                    component="engine_core",
                    event_name="scheduled",
                    timestamp_ns=timestamp_ns,
                    preemption_epoch=0,
                    end_span_id=state.queue_span_id,
                    sample_index=0,
                    metadata={
                        "prompt_tokens_total": prompt_tokens_total,
                        "prompt_tokens_cached": prompt_tokens_cached,
                        "prompt_tokens_to_compute": (
                            prompt_tokens_total - prompt_tokens_cached
                        ),
                    },
                )
            )
            active_span_id = self._hooks.new_span_id()
            if scheduled is None or active_span_id is None:
                return False
            started = self._hooks.emit_event(
                EventDraft(
                    trace_id=state.identity.trace_id,
                    lifecycle_id=state.identity.engine_lifecycle_id,
                    parent_lifecycle_id=f"{state.identity.trace_id}:r",
                    scope="engine_sample",
                    component="engine_core",
                    event_name=f"{compute_kind}_started",
                    timestamp_ns=timestamp_ns,
                    preemption_epoch=0,
                    start_span_id=active_span_id,
                    sample_index=0,
                )
            )
            if started is None:
                return False
            if (
                self._hooks.emit_edge(
                    EdgeDraft(
                        trace_id=state.identity.trace_id,
                        from_event_id=state.queue_started.event_id,
                        to_event_id=scheduled.record_id,
                        edge_kind="program_order",
                        evidence_source="instrumented_execution_context",
                    )
                )
                is None
                or self._hooks.emit_edge(
                    EdgeDraft(
                        trace_id=state.identity.trace_id,
                        from_event_id=scheduled.record_id,
                        to_event_id=started.record_id,
                        edge_kind="program_order",
                        evidence_source="instrumented_execution_context",
                    )
                )
                is None
            ):
                return False
            state.active_started = BaseEventRef(started.record_id, timestamp_ns)
            state.active_span_id = active_span_id
            state.prompt_tokens_computed = min(
                prompt_tokens_total, prompt_tokens_cached + scheduled_tokens
            )
            state.prefill_chunk_count = int(compute_kind == "prefill")
            return True

    def emit_runtime_preempted(
        self,
        runtime_request_id: str,
        recovery_epoch: int,
        *,
        timestamp_ns: int,
    ) -> BaseEventRef | None:
        """Close the active real scheduler span at committed preemption."""

        with self._lock:
            state = self._runtime_states.get(runtime_request_id)
            if (
                state is None
                or state.active_started is None
                or state.active_span_id is None
            ):
                logger.warning(
                    "KV-recovery preempt for %s epoch=%s dropped: no active "
                    "compute span (state=%s)",
                    runtime_request_id,
                    recovery_epoch,
                    "missing" if state is None else "no active span",
                )
                return None
            active_started = state.active_started
            active_span_id = state.active_span_id
            prompt_tokens_computed = state.prompt_tokens_computed
            prefill_chunk_count = max(1, state.prefill_chunk_count)
        result = self.emit_preempted_and_requeued(
            runtime_request_id,
            recovery_epoch,
            timestamp_ns=timestamp_ns,
            active_span_start_event_id=active_started.event_id,
            active_span_id=active_span_id,
            prompt_tokens_computed=prompt_tokens_computed,
            prefill_chunk_count=prefill_chunk_count,
        )
        if result is not None:
            with self._lock:
                state = self._runtime_states.get(runtime_request_id)
                episode = self._episodes.get((runtime_request_id, recovery_epoch))
                if state is not None and episode is not None:
                    state.queue_started = episode.requeued
                    state.queue_span_id = episode.queue_span_id
                    state.active_started = None
                    state.active_span_id = None
                    state.prompt_tokens_computed = 0
                    state.prefill_chunk_count = 0
        return result

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

    def emit_runtime_admission_started(
        self,
        runtime_request_id: str,
        recovery_epoch: int,
        *,
        timestamp_ns: int,
    ) -> BaseEventRef | None:
        """Capture the real restored-request admission boundary."""

        return self.emit_admission_started(
            runtime_request_id,
            recovery_epoch,
            timestamp_ns=timestamp_ns,
        )

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

    def emit_runtime_resumed(
        self,
        runtime_request_id: str,
        recovery_epoch: int,
        *,
        timestamp_ns: int,
        prompt_tokens_total: int,
        prompt_tokens_cached: int,
    ) -> BaseEventRef | None:
        """Capture the committed PREEMPTED-to-RUNNING transition."""

        if prompt_tokens_total < 1:
            return None
        prompt_tokens_cached = min(
            max(0, prompt_tokens_cached), prompt_tokens_total - 1
        )
        result = self.emit_resumed(
            runtime_request_id,
            recovery_epoch,
            timestamp_ns=timestamp_ns,
            prompt_tokens_total=prompt_tokens_total,
            prompt_tokens_cached=prompt_tokens_cached,
            prompt_tokens_to_compute=prompt_tokens_total - prompt_tokens_cached,
        )
        if result is not None:
            with self._lock:
                state = self._runtime_states.get(runtime_request_id)
                if state is not None:
                    state.prompt_tokens_computed = prompt_tokens_cached
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
                logger.debug(
                    "KV-recovery emit_first_compute rejected for %s epoch=%s: "
                    "identity=%s episode=%s resumed=%s first_compute=%s kind=%s",
                    runtime_request_id,
                    recovery_epoch,
                    identity is not None,
                    episode is not None,
                    episode.resumed is not None if episode else None,
                    episode.first_compute is not None if episode else None,
                    compute_kind,
                )
                return None
            span_id = self._hooks.new_span_id()
            if span_id is None:
                logger.debug(
                    "KV-recovery emit_first_compute no span id for %s",
                    runtime_request_id,
                )
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
            state = self._runtime_states.get(runtime_request_id)
            if state is not None:
                state.active_started = result
                state.active_span_id = span_id
                if compute_kind == "prefill":
                    state.prefill_chunk_count += 1
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
            self._runtime_states.pop(runtime_request_id, None)
            for key in tuple(self._episodes):
                if key[0] == runtime_request_id:
                    self._episodes.pop(key, None)


@dataclass(frozen=True)
class KVRecoveryRuntimeABI:
    """Late-bound constructors from ``vllm.v1.kv_recovery_profile``."""

    identity_type: Callable[..., Any]
    logical_block_type: Callable[..., Any]
    transfer_context_type: Callable[..., Any]
    compute_context_type: Callable[..., Any]
    receipt_type: Callable[..., Any]
    bounded_worker_observer_type: Callable[..., Any]
    canonical_block_set_id: Callable[[Any, tuple[Any, ...]], str]

    @classmethod
    def load(cls) -> KVRecoveryRuntimeABI:
        """Import the runtime ABI only when an explicit caller requests it."""

        from vllm.v1 import kv_recovery_profile as runtime

        return cls(
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
                        preemption_epoch=context.identity.recovery_epoch or 0,
                        start_span_id=span_id,
                        sample_index=0,
                        metadata=self._communication_metadata(attempt),
                    )
                )
                start_event_id = ref.record_id if ref is not None else None
            if start_event_id is None:
                self._profile.drop("recovery_event", timestamp_ns)
                return
            if context.identity.base_preempted_event_id is not None:
                # Episode-driven restore: link the transfer span back to the
                # committed preempted event.
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
        if (
            context.operation == "h2d_restore"
            and context.identity.preempt_profile_record_id is not None
        ):
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
                    preemption_epoch=context.identity.recovery_epoch or 0,
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
        if pending.restore_start_profile_record_id is None:
            # Unassociated H2D (block-level tiering migration of a running
            # request): the transfer evidence is complete, but there is no
            # preemption episode to attach an admission chain to, so no
            # receipt is produced.
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
    ) -> None:
        """Write the worker child observation with its scheduler predecessor."""

        try:
            if context.identity.recovery_epoch is None or context.compute_kind not in {
                "prefill",
                "decode",
            }:
                raise ValueError("invalid first-compute sidecar")
            _require_event_id(
                context.base_phase_start_event_id,
                "base_phase_start_event_id",
            )
            identity = context.identity
            self._profile.write(
                "recovery_event",
                timestamp_ns,
                **self._request_fields(identity),
                stage="first_prefill_or_decode",
                occurrence=0,
                base_event_id=context.base_phase_start_event_id,
                base_admission_started_event_id=None,
                from_profile_event_id=context.admission_profile_record_id,
                transfer_id=context.transfer_id,
                block_set_id=context.block_set_id,
                bytes_moved=context.bytes_moved,
                requeue_reason=None,
                compute_kind=context.compute_kind,
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
            "communication_mapping": KV_RECOVERY_COMMUNICATION_MODE,
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

    def request_started(self, runtime_request_id: str) -> None:
        """Register the runtime request at the connector entry callback."""

        if self._closed:
            return
        try:
            timestamp_ns = self._clock_ns()
            if not self._bridge.register_runtime_request(
                self._run_id,
                runtime_request_id,
                timestamp_ns=timestamp_ns,
            ):
                self._profile.drop("recovery_event", timestamp_ns)
        except Exception:  # noqa: BLE001 - serving-side evidence is fail-open.
            self._profile.drop("recovery_event", None)

    def request_scheduled(
        self,
        runtime_request_id: str,
        compute_kind: str,
        scheduled_tokens: int,
        prompt_tokens_total: int,
        prompt_tokens_cached: int,
    ) -> None:
        """Capture the real scheduler step used as the preemption predecessor."""

        if self._closed:
            return
        try:
            timestamp_ns = self._clock_ns()
            if not self._bridge.emit_runtime_scheduled(
                runtime_request_id,
                timestamp_ns=timestamp_ns,
                compute_kind=compute_kind,
                scheduled_tokens=scheduled_tokens,
                prompt_tokens_total=prompt_tokens_total,
                prompt_tokens_cached=prompt_tokens_cached,
            ):
                self._profile.drop("recovery_event", timestamp_ns)
        except Exception:  # noqa: BLE001 - serving-side evidence is fail-open.
            self._profile.drop("recovery_event", None)

    def request_preempted(
        self, runtime_request_id: str, recovery_epoch: int
    ) -> str | None:
        if self._closed or recovery_epoch < 1:
            logger.warning(
                "KV-recovery request_preempted(%s, %s) rejected (closed=%s)",
                runtime_request_id,
                recovery_epoch,
                self._closed,
            )
            return None
        identity = self._bridge.request_identity(runtime_request_id)
        base_event = self._bridge.preempted_event(runtime_request_id, recovery_epoch)
        if identity is not None and base_event is None:
            try:
                base_event = self._bridge.emit_runtime_preempted(
                    runtime_request_id,
                    recovery_epoch,
                    timestamp_ns=self._clock_ns(),
                )
            except Exception:  # noqa: BLE001 - serving-side evidence is fail-open.
                base_event = None
        if identity is None or base_event is None:
            logger.warning(
                "KV-recovery request_preempted(%s, %s) dropped: identity=%s base_event=%s",
                runtime_request_id,
                recovery_epoch,
                identity is not None,
                base_event is not None,
            )
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
            logger.debug(
                "KV-recovery %s context omitted for %s: %s",
                operation,
                runtime_request_id,
                "closed" if self._closed else "empty coordinates",
            )
            return None
        base_identity = self._bridge.request_identity(runtime_request_id)
        if base_identity is None:
            logger.warning(
                "KV-recovery %s context omitted for %s: no base identity",
                operation,
                runtime_request_id,
            )
            self._profile.drop("block_set_chunk", None)
            return None
        episode = self._episodes.get(runtime_request_id)
        if operation == "h2d_restore":
            if episode is None:
                # The runtime performs H2D both for preemption recovery (an
                # episode exists) and for block-level tiering migration of a
                # still-running request (no episode). Record the latter as an
                # unassociated transfer: it carries no preempt/admission chain
                # but is still real H2D migration evidence.
                logger.warning(
                    "KV-recovery %s context unassociated for %s (no episode)",
                    operation,
                    runtime_request_id,
                )
                recovery_epoch = None
                episode_id = None
                preempted_event_id = None
            else:
                recovery_epoch = episode.recovery_epoch
                episode_id = f"{base_identity.engine_lifecycle_id}:k:{recovery_epoch}"
                preempted_event_id = episode.preempted_event.event_id
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
            block_set_id = self._abi.canonical_block_set_id(identity, logical_blocks)
            context = self._abi.transfer_context_type(
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
        chunk_size = _MAX_BLOCK_ROWS_PER_CHUNK_BYTE_BUDGET
        chunk_count = (len(logical_blocks) + chunk_size - 1) // chunk_size
        for chunk_index in range(chunk_count):
            start = chunk_index * chunk_size
            chunk = logical_blocks[start : start + chunk_size]
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
            if receipt.identity.recovery_epoch is None:
                # Unassociated H2D (block-level tiering migration) produces no
                # recovery episode; ignore its receipt without failing closed.
                continue
            episode = self._episodes.get(runtime_request_id)
            if (
                episode is None
                or episode.context is None
                or episode.receipt is not None
                or receipt.identity != episode.context.identity
                or receipt.block_set_id != episode.context.block_set_id
                or receipt.identity.recovery_epoch != episode.recovery_epoch
            ):
                logger.debug(
                    "KV-recovery receipt dropped for %s epoch=%s: episode=%s "
                    "ctx=%s receipt_epoch=%s",
                    runtime_request_id,
                    receipt.identity.recovery_epoch,
                    episode is not None,
                    episode.context is not None if episode else None,
                    receipt.identity.recovery_epoch,
                )
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
        if event is None:
            try:
                event = self._bridge.emit_runtime_admission_started(
                    runtime_request_id,
                    recovery_epoch,
                    timestamp_ns=wakeup_timestamp_ns,
                )
            except Exception:  # noqa: BLE001 - serving-side evidence is fail-open.
                event = None
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
        self,
        runtime_request_id: str,
        recovery_epoch: int,
        compute_kind: str,
        prompt_tokens_total: int = 1,
        prompt_tokens_cached: int = 0,
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
            or compute_kind not in {"prefill", "decode"}
        ):
            return None
        resumed_event = self._bridge.resumed_event(runtime_request_id, recovery_epoch)
        if resumed_event is None:
            try:
                resumed_event = self._bridge.emit_runtime_resumed(
                    runtime_request_id,
                    recovery_epoch,
                    timestamp_ns=self._clock_ns(),
                    prompt_tokens_total=prompt_tokens_total,
                    prompt_tokens_cached=prompt_tokens_cached,
                )
            except Exception:  # noqa: BLE001 - serving-side evidence is fail-open.
                resumed_event = None
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
            first_compute_timestamp_ns = max(
                resumed_event.timestamp_ns,
                self._clock_ns(),
            )
            first_compute_event = self._bridge.emit_first_compute(
                runtime_request_id,
                recovery_epoch,
                timestamp_ns=first_compute_timestamp_ns,
                compute_kind=compute_kind,
            )
            if first_compute_event is None:
                raise ValueError("base first-compute event was not emitted")
            context = self._abi.compute_context_type(
                identity=episode.receipt.identity,
                transfer_id=episode.receipt.transfer_id,
                block_set_id=episode.receipt.block_set_id,
                bytes_moved=episode.receipt.bytes_moved,
                admission_profile_record_id=profile_id,
                compute_kind=compute_kind,
                base_phase_start_event_id=first_compute_event.event_id,
            )
        except Exception:
            logger.debug(
                "KV-recovery request_admitted compute-context failed for %s epoch=%s",
                runtime_request_id,
                recovery_epoch,
                exc_info=True,
            )
            self._profile.drop("recovery_event", resumed_event.timestamp_ns)
            return None
        logger.debug(
            "KV-recovery request_admitted SUCCESS compute-context for %s epoch=%s",
            runtime_request_id,
            recovery_epoch,
        )
        self._episodes.pop(runtime_request_id, None)
        return context

    def request_terminal(self, runtime_request_id: str) -> None:
        episode = self._episodes.pop(runtime_request_id, None)
        if episode is not None:
            self._profile.drop("recovery_event", None)
        self._bridge.request_terminal(runtime_request_id)

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
    """Late-bound vLLM observer factory controlled by runtime configuration."""

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

    def reinitialize_after_fork(self) -> None:
        if not self._hooks.reinitialize_after_fork():
            raise RuntimeError("trace exporter could not reinitialize after fork")

    def create_scheduler_observer(self) -> Any | None:
        if not self._runtime_config_enabled():
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

    def create_worker_observer(self) -> Any | None:
        if not self._runtime_config_enabled():
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

    def _runtime_config_enabled(self) -> bool:
        return (
            self._hooks.enabled
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


@dataclass(frozen=True)
class ExpectedKVRecoveryEpisode:
    """Exact joins required for one paired seven-stage recovery episode."""

    h2d: ExpectedH2DRecovery
    run_id: str
    runtime_request_id: str
    resumed_event_id: str
    first_compute_base_event_id: str
    compute_kind: str
    requeue_reasons: tuple[str, ...]
    process_uuids: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_hex32(self.run_id, "run_id")
        _require_event_id(self.resumed_event_id, "resumed_event_id")
        _require_event_id(
            self.first_compute_base_event_id, "first_compute_base_event_id"
        )
        if self.compute_kind not in {"prefill", "decode"}:
            raise ValueError("compute_kind must be prefill or decode")
        if not self.process_uuids or len(set(self.process_uuids)) != len(
            self.process_uuids
        ):
            raise ValueError("process_uuids must be a nonempty unique roster")
        for process_uuid in self.process_uuids:
            _require_hex32(process_uuid, "process_uuid")


@dataclass(frozen=True)
class NormalizedKVRecoveryEpisode:
    h2d: NormalizedH2DRecovery
    profile_event_ids: tuple[str, ...]
    requeue_count: int


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
    event_rows = [row for row in rows if row.get("record_type") == "event"]
    events = {
        row.get("event_id"): row
        for row in event_rows
        if isinstance(row.get("event_id"), str)
    }
    if len(events) != len(event_rows):
        raise ValueError("base event IDs are missing or duplicated")
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
            expected.trace_id,
            expected.preempted_event_id,
            start_id,
            "data_dependency",
            KV_RECOVERY_H2D_EVIDENCE,
        ),
        (
            expected.trace_id,
            start_id,
            done_id,
            "program_order",
            "instrumented_execution_context",
        ),
        (
            expected.trace_id,
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
                edge.get("trace_id"),
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


def normalize_kv_recovery_episode(
    base_records: Iterable[Mapping[str, object]],
    profile_records: Iterable[Mapping[str, object]],
    expected: ExpectedKVRecoveryEpisode,
    *,
    profile_evidence_complete: bool,
) -> NormalizedKVRecoveryEpisode:
    """Validate a paired process roster and explicit seven-stage profile chain."""

    base_rows = tuple(base_records)
    profile_rows = tuple(profile_records)
    h2d = normalize_h2d_recovery(
        base_rows,
        expected.h2d,
        profile_evidence_complete=profile_evidence_complete,
    )
    expected_processes = set(expected.process_uuids)
    _validate_process_roster(base_rows, "process_start", expected_processes)
    _validate_process_roster(base_rows, "process_summary", expected_processes)
    _validate_process_roster(profile_rows, "profile_start", expected_processes)
    _validate_process_roster(profile_rows, "profile_summary", expected_processes)
    _validate_shard_content_digests(
        base_rows,
        expected_processes,
        summary_type="process_summary",
        encoder=canonical_json_line,
    )
    _validate_shard_content_digests(
        profile_rows,
        expected_processes,
        summary_type="profile_summary",
        encoder=profile_record_line,
    )
    if any(row.get("record_type") == "loss_interval" for row in profile_rows):
        raise ValueError("profile evidence contains loss")
    _validate_profile_ledgers(profile_rows, expected_processes)

    profile_data = [
        row
        for row in profile_rows
        if row.get("record_type")
        in {"block_set_chunk", "wait_set_chunk", "transfer_event", "recovery_event"}
    ]
    record_ids = [row.get("record_id") for row in profile_data]
    if any(not isinstance(record_id, str) for record_id in record_ids) or len(
        set(record_ids)
    ) != len(record_ids):
        raise ValueError("profile record IDs are missing or duplicated")

    episode_id = f"{expected.h2d.engine_lifecycle_id}:k:{expected.h2d.recovery_epoch}"
    milestones = [
        row
        for row in profile_data
        if row.get("record_type") == "recovery_event"
        and row.get("run_id") == expected.run_id
        and row.get("trace_id") == expected.h2d.trace_id
        and row.get("engine_lifecycle_id") == expected.h2d.engine_lifecycle_id
        and row.get("runtime_request_id") == expected.runtime_request_id
        and row.get("recovery_epoch") == expected.h2d.recovery_epoch
        and row.get("episode_id") == episode_id
    ]
    by_stage: dict[str, list[Mapping[str, object]]] = {}
    for row in milestones:
        stage = row.get("stage")
        if not isinstance(stage, str):
            raise TypeError("recovery event stage is missing")
        by_stage.setdefault(stage, []).append(row)
    unique_stages = (
        "preempt",
        "restore_start",
        "restore_done",
        "scheduler_wakeup",
        "admission",
        "first_prefill_or_decode",
    )
    if any(len(by_stage.get(stage, ())) != 1 for stage in unique_stages):
        raise ValueError("unique recovery stage is missing or duplicated")
    if set(by_stage) - {*unique_stages, "requeue"}:
        raise ValueError("recovery episode contains an unknown stage")
    requeues = sorted(
        by_stage.get("requeue", ()), key=lambda row: row.get("occurrence")
    )
    if [row.get("occurrence") for row in requeues] != list(range(len(requeues))):
        raise ValueError("requeue occurrence sequence is not contiguous")
    if tuple(row.get("requeue_reason") for row in requeues) != (
        expected.requeue_reasons
    ):
        raise ValueError("requeue reasons differ from the exact expectation")
    chain = [
        by_stage["preempt"][0],
        by_stage["restore_start"][0],
        by_stage["restore_done"][0],
        by_stage["scheduler_wakeup"][0],
        *requeues,
        by_stage["admission"][0],
        by_stage["first_prefill_or_decode"][0],
    ]
    previous_id: object = None
    previous_timestamp = 0
    for index, row in enumerate(chain):
        if row.get("from_profile_event_id") != previous_id:
            raise ValueError("profile predecessor chain is broken")
        timestamp = row.get("timestamp_ns")
        if not _is_uint64(timestamp) or (index and timestamp < previous_timestamp):
            raise ValueError("profile stage timestamps are inverted")
        previous_timestamp = timestamp
        previous_id = row.get("record_id")

    preempt, restore_start, restore_done, wakeup = chain[:4]
    admission, first_compute = chain[-2:]
    if preempt.get("base_event_id") != expected.h2d.preempted_event_id:
        raise ValueError("profile preempt base association differs")
    if restore_start.get("base_event_id") != h2d.start_event_id:
        raise ValueError("restore_start base association differs")
    if restore_done.get("base_event_id") != h2d.done_event_id:
        raise ValueError("restore_done base association differs")
    if wakeup.get("base_event_id") is not None or any(
        row.get("base_event_id") is not None for row in requeues
    ):
        raise ValueError("profile-only stage contains a base association")
    if (
        admission.get("base_event_id") != expected.resumed_event_id
        or admission.get("base_admission_started_event_id")
        != expected.h2d.admission_started_event_id
    ):
        raise ValueError("admission base associations differ")
    if (
        first_compute.get("base_event_id") != expected.first_compute_base_event_id
        or first_compute.get("compute_kind") != expected.compute_kind
        or first_compute.get("child_observation_kind") != "worker_model_forward_entry"
        or first_compute.get("base_association_kind") != "phase_child_observation"
        or first_compute.get("base_association_evidence")
        != "instrumented_execution_context"
    ):
        raise ValueError("first compute child association differs")

    events = {
        row.get("event_id"): row
        for row in base_rows
        if row.get("record_type") == "event"
    }
    for event_id, event_name in (
        (expected.resumed_event_id, "resumed"),
        (expected.first_compute_base_event_id, f"{expected.compute_kind}_started"),
    ):
        event = events.get(event_id)
        if (
            event is None
            or event.get("event_name") != event_name
            or event.get("trace_id") != expected.h2d.trace_id
            or event.get("lifecycle_id") != expected.h2d.engine_lifecycle_id
            or event.get("preemption_epoch") != expected.h2d.recovery_epoch
        ):
            raise ValueError("later base phase association is missing or drifted")

    transfer_rows = [
        row
        for row in profile_data
        if row.get("record_type") == "transfer_event"
        and row.get("transfer_id") == expected.h2d.transfer_id
    ]
    if [row.get("transfer_phase") for row in transfer_rows] != ["submit", "done"]:
        raise ValueError("profile transfer pair is missing, reordered, or duplicated")
    if (
        transfer_rows[0].get("timestamp_ns") != restore_start.get("timestamp_ns")
        or transfer_rows[1].get("timestamp_ns") != restore_done.get("timestamp_ns")
        or transfer_rows[1].get("bytes_moved") != h2d.bytes_moved
    ):
        raise ValueError("restore milestones differ from transfer evidence")
    for row in chain[1:]:
        if (
            row.get("transfer_id") != expected.h2d.transfer_id
            or row.get("block_set_id") != expected.h2d.block_set_id
            or (
                row.get("stage") != "restore_start"
                and row.get("bytes_moved") != h2d.bytes_moved
            )
        ):
            raise ValueError("recovery stage transfer identity drifted")
    if restore_start.get("bytes_moved") is not None:
        raise ValueError("restore_start must not report bytes")

    block_chunks = [
        row
        for row in profile_data
        if row.get("record_type") == "block_set_chunk"
        and row.get("block_set_id") == expected.h2d.block_set_id
        and row.get("episode_id") == episode_id
    ]
    if not block_chunks:
        raise ValueError("logical recovery block set is missing")
    block_chunks.sort(key=lambda row: row.get("chunk_index"))
    chunk_count = len(block_chunks)
    if [row.get("chunk_index") for row in block_chunks] != list(range(chunk_count)):
        raise ValueError("block chunks are not contiguous")
    if any(row.get("chunk_count") != chunk_count for row in block_chunks):
        raise ValueError("block chunk count differs")
    blocks = [block for row in block_chunks for block in row.get("blocks", ())]
    if (
        not blocks
        or any(row.get("total_block_count") != len(blocks) for row in block_chunks)
        or len({(row.get("group_index"), row.get("logical_ordinal")) for row in blocks})
        != len(blocks)
        or len({row.get("logical_block_id") for row in blocks}) != len(blocks)
    ):
        raise ValueError("logical recovery block rows are incomplete or duplicated")
    return NormalizedKVRecoveryEpisode(
        h2d=h2d,
        profile_event_ids=tuple(row["record_id"] for row in chain),
        requeue_count=len(requeues),
    )


def _validate_process_roster(
    rows: tuple[Mapping[str, object], ...],
    record_type: str,
    expected_processes: set[str],
) -> None:
    observed = [
        row.get("process_uuid") for row in rows if row.get("record_type") == record_type
    ]
    if len(observed) != len(expected_processes) or set(observed) != expected_processes:
        raise ValueError(f"{record_type} process roster differs")


def _validate_shard_content_digests(
    rows: tuple[Mapping[str, object], ...],
    expected_processes: set[str],
    *,
    summary_type: str,
    encoder: Callable[[Mapping[str, object]], bytes],
) -> None:
    """Recompute each parsed shard digest from its canonical record bytes."""

    for process_uuid in expected_processes:
        process_rows = [row for row in rows if row.get("process_uuid") == process_uuid]
        summaries = [
            row for row in process_rows if row.get("record_type") == summary_type
        ]
        if len(summaries) != 1:
            raise ValueError(f"{summary_type} process roster differs")
        content_hash = hashlib.sha256()
        for row in process_rows:
            if row.get("record_type") != summary_type:
                content_hash.update(encoder(row))
        if summaries[0].get("content_sha256") != content_hash.hexdigest():
            raise ValueError(f"{summary_type} content digest differs")


def _validate_profile_ledgers(
    rows: tuple[Mapping[str, object], ...], expected_processes: set[str]
) -> None:
    categories = (
        "block_set_chunk",
        "wait_set_chunk",
        "transfer_event",
        "recovery_event",
    )
    for process_uuid in expected_processes:
        data = [
            row
            for row in rows
            if row.get("process_uuid") == process_uuid
            and row.get("record_type") in categories
        ]
        summaries = [
            row
            for row in rows
            if row.get("process_uuid") == process_uuid
            and row.get("record_type") == "profile_summary"
        ]
        assert len(summaries) == 1
        summary = summaries[0]
        if (
            summary.get("close_outcome") != "drained"
            or summary.get("dropped_data_count") != 0
            or summary.get("dropped_control_count") != 0
            or summary.get("writer_failure_count") != 0
            or summary.get("attempted_data_count") != len(data)
            or sorted(row.get("record_seq") for row in data) != list(range(len(data)))
        ):
            raise ValueError("profile process ledger is incomplete")
        for category in categories:
            key = f"written_{category}_count"
            if summary.get(key) != sum(
                row.get("record_type") == category for row in data
            ):
                raise ValueError("profile summary category count differs")


__all__ = [
    "BaseEventRef",
    "BaseLifecycleBridge",
    "BoundedKVRecoveryProfileLedger",
    "ExpectedH2DRecovery",
    "ExpectedKVRecoveryEpisode",
    "KVRecoveryObserverFactoryAdapter",
    "KVRecoveryRuntimeABI",
    "KVRecoverySchedulerAdapter",
    "KVRecoveryWorkerEvidenceAdapter",
    "NormalizedH2DRecovery",
    "NormalizedKVRecoveryEpisode",
    "ProfileLossInterval",
    "ProfileRecord",
    "RequestLifecycleIdentity",
    "RuntimeBaseLifecycleBridge",
    "normalize_h2d_recovery",
    "normalize_kv_recovery_episode",
]
