"""Observer-only request lifecycle seam for Issue #19.

The runtime calls this object only when the existing trace exporter is
explicitly enabled.  Callbacks are bounded and fail-open; they observe request
and worker-generation transitions but never change scheduling or ownership.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass

from vllm_request_lifecycle_profiler.kv_recovery_profile_protocol import (
    MAX_PROFILE_DATA_RECORDS,
)
from vllm_request_lifecycle_profiler.kv_recovery_runtime import (
    RuntimeBaseLifecycleBridge,
)
from vllm_request_lifecycle_profiler.runtime_hooks import RuntimeLifecycleHooks
from vllm_request_lifecycle_profiler.runtime_protocol import EventDraft

TERMINAL_CAUSES = frozenset(
    {
        "complete",
        "client_disconnect",
        "client_timeout",
        "explicit_cancel",
        "engine_failure",
        "error",
    }
)
RESOURCE_TRANSITIONS = frozenset(
    {"acquire", "transfer_pending", "release", "policy_retain", "invalidate"}
)
_RESOURCE_EVENTS = {
    "acquire": "resource_acquired",
    "transfer_pending": "resource_transfer_pending",
    "release": "resource_released",
    "policy_retain": "resource_policy_retained",
    "invalidate": "resource_invalidated",
}


@dataclass(frozen=True)
class ResourceObservation:
    runtime_request_id: str
    resource_type: str
    resource_id: str
    transition: str
    worker_generation: str
    resource_units: int
    timestamp_ns: int


class Issue19LifecycleObserver:
    """Bounded adapter shared by the generic runtime call sites."""

    def __init__(
        self,
        hooks: RuntimeLifecycleHooks,
        bridge: RuntimeBaseLifecycleBridge,
        run_id: str,
        *,
        capacity: int = MAX_PROFILE_DATA_RECORDS,
        clock_ns=time.monotonic_ns,
    ) -> None:
        self._hooks = hooks
        self._bridge = bridge
        self._run_id = run_id
        self._capacity = capacity
        self._clock_ns = clock_ns
        self._lock = threading.Lock()
        self._active_requests: set[str] = set()
        self._abort_attempts: dict[str, int] = {}
        self._resource_observations: list[ResourceObservation] = []

    @property
    def abort_attempts(self) -> dict[str, int]:
        with self._lock:
            return dict(self._abort_attempts)

    @property
    def resource_observations(self) -> tuple[ResourceObservation, ...]:
        with self._lock:
            return tuple(self._resource_observations)

    def snapshot(self) -> dict[str, object]:
        """Return a privacy-minimized control-plane state snapshot."""

        with self._lock:
            return {
                "active_request_ids": sorted(self._active_requests),
                "abort_attempts": dict(sorted(self._abort_attempts.items())),
                "resource_observation_count": len(self._resource_observations),
                "resource_observation_scope": "process-local",
            }

    def request_started(self, runtime_request_id: str) -> None:
        try:
            timestamp_ns = self._clock_ns()
            if self._bridge.register_runtime_request(
                self._run_id, runtime_request_id, timestamp_ns=timestamp_ns
            ):
                with self._lock:
                    if len(self._active_requests) < self._capacity:
                        self._active_requests.add(runtime_request_id)
        except Exception:  # noqa: BLE001 - serving observation must fail open.
            return

    def abort_attempt(self, runtime_request_id: str) -> None:
        try:
            with self._lock:
                if (
                    runtime_request_id in self._abort_attempts
                    or len(self._abort_attempts) < self._capacity
                ):
                    self._abort_attempts[runtime_request_id] = (
                        self._abort_attempts.get(runtime_request_id, 0) + 1
                    )
        except Exception:  # noqa: BLE001 - serving observation must fail open.
            return

    def request_terminal(
        self,
        runtime_request_id: str,
        terminal_cause: str,
        *,
        generated_tokens_total: int = 0,
    ) -> None:
        if terminal_cause not in TERMINAL_CAUSES:
            return
        try:
            self._bridge.emit_runtime_terminal(
                runtime_request_id,
                terminal_cause,
                timestamp_ns=self._clock_ns(),
                generated_tokens_total=generated_tokens_total,
            )
        except Exception:  # noqa: BLE001 - serving observation must fail open.
            return
        finally:
            with self._lock:
                self._active_requests.discard(runtime_request_id)

    def engine_failure(self, runtime_request_ids: Iterable[str]) -> None:
        try:
            request_ids = tuple(runtime_request_ids)[: self._capacity]
        except Exception:  # noqa: BLE001 - serving observation must fail open.
            return
        for runtime_request_id in request_ids:
            self.request_terminal(runtime_request_id, "engine_failure")

    def worker_generation_exit(
        self,
        worker_name: str,
        *,
        worker_pid: int | None,
        exit_code: int | None,
    ) -> None:
        """Record an engine-wide worker-generation failure boundary."""

        try:
            generation = f"{worker_name}:{worker_pid}"
            trace_id = hashlib.sha256(
                f"{self._run_id}\0{generation}".encode()
            ).hexdigest()[:32]
            self._hooks.emit_event(
                EventDraft(
                    trace_id=trace_id,
                    lifecycle_id=f"{trace_id}:r",
                    parent_lifecycle_id=None,
                    scope="root_request",
                    component="frontend",
                    event_name="error",
                    timestamp_ns=self._clock_ns(),
                    metadata={
                        "terminal_cause": "engine_failure",
                        "worker_generation": generation,
                        "worker_exit_code": exit_code,
                    },
                )
            )
        except Exception:  # noqa: BLE001 - serving observation must fail open.
            return

    def resource_transition(
        self,
        runtime_request_id: str,
        resource_type: str,
        resource_id: str,
        transition: str,
        worker_generation: str,
        resource_units: int = 1,
    ) -> None:
        """Persist one bounded request-scoped ownership transition."""

        if transition not in RESOURCE_TRANSITIONS or not (
            isinstance(resource_units, int)
            and not isinstance(resource_units, bool)
            and resource_units >= 1
        ):
            return
        try:
            timestamp_ns = self._clock_ns()
            observation = ResourceObservation(
                runtime_request_id=runtime_request_id,
                resource_type=resource_type,
                resource_id=resource_id,
                transition=transition,
                worker_generation=worker_generation,
                resource_units=resource_units,
                timestamp_ns=timestamp_ns,
            )
            trace_id = hashlib.sha256(
                f"{self._run_id}\0{runtime_request_id}".encode()
            ).hexdigest()[:32]
            with self._lock:
                if len(self._resource_observations) >= self._capacity:
                    return
                emitted = self._hooks.emit_event(
                    EventDraft(
                        trace_id=trace_id,
                        lifecycle_id=f"{trace_id}:e:0",
                        parent_lifecycle_id=f"{trace_id}:r",
                        scope="engine_sample",
                        component="engine_core",
                        event_name=_RESOURCE_EVENTS[transition],
                        timestamp_ns=timestamp_ns,
                        preemption_epoch=0,
                        sample_index=0,
                        metadata={
                            "runtime_request_id": runtime_request_id,
                            "resource_type": resource_type,
                            "resource_id": resource_id,
                            "resource_transition": transition,
                            "resource_units": resource_units,
                            "worker_generation": worker_generation,
                        },
                    )
                )
                if emitted is not None:
                    self._resource_observations.append(observation)
        except Exception:  # noqa: BLE001 - serving observation must fail open.
            return
