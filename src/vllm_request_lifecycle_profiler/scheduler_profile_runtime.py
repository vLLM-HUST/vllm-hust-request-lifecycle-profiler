"""Fail-open runtime adapter for the audited scheduler profile hooks."""

from __future__ import annotations

import atexit
import logging
import os
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from vllm_request_lifecycle_profiler.runtime_hooks import (
    TRACE_CLOCK_DOMAIN_ID_ENV,
    TRACE_COMMUNICATION_MODE_ENV,
    TRACE_DEVICE_COMMIT_ENV,
    TRACE_PARENT_COMMIT_ENV,
    TRACE_PROCESS_INSTANCE_ID_ENV,
    TRACE_RUNTIME_COMMIT_ENV,
)
from vllm_request_lifecycle_profiler.scheduler_profile import (
    SCHEDULER_RUNTIME_PROFILE_ID,
    NullSchedulerProfileExporter,
    ProcessLocalExporterIdentity,
    SchedulerCloseResult,
    SchedulerCycleRef,
    SchedulerExporterConfig,
    SchedulerProfileExporter,
    SchedulerProvenance,
    SchedulerShardScope,
    create_scheduler_profile_exporter,
)

if TYPE_CHECKING:
    from vllm_request_lifecycle_profiler.runtime_hooks import RuntimeLifecycleHooks

logger = logging.getLogger(__name__)

SCHEDULER_EXPORT_ENV = "VLLM_RLP_SCHEDULER_PROFILE_PATH"
SCHEDULER_EXPERIMENT_RUN_ID_ENV = "VLLM_RLP_EXPERIMENT_RUN_ID"
SCHEDULER_SERVER_INSTANCE_ID_ENV = "VLLM_RLP_SERVER_INSTANCE_ID"
SCHEDULER_SHARD_ID_ENV = "VLLM_RLP_SCHEDULER_SHARD_ID"

AUDITED_RUNTIME_CORE_COMMIT = "ad7125a431e176d4161099480a66f0169609a690"
AUDITED_DEVICE_PLUGIN_COMMIT = "80610e4438dba05011b05f89fc45d91e96992671"
_CLOCK_BRIDGE_MAX_BRACKET_NS = 100_000

_TOKEN_BUCKETS = tuple(
    (queue, mode)
    for queue in ("running", "waiting", "skipped_waiting")
    for mode in ("not_limited", "clipped", "stopped_no_chunk")
)
_CAP_BUCKETS = tuple(
    (queue, mode)
    for queue in ("running", "waiting", "skipped_waiting")
    for mode in ("not_limited", "stopped_at_cap")
)


@dataclass(frozen=True, slots=True)
class SchedulerRuntimeProfile:
    """Resolved facts for the only audited v1 runtime path."""

    max_concurrent_batches: int
    async_scheduling: bool
    distributed_executor_backend: str
    tensor_parallel_size: int
    pipeline_parallel_size: int
    data_parallel_size: int
    decode_context_parallel_size: int
    eager_execution: bool
    decoder_only_generation: bool
    multimodal: bool
    speculative_decoding: bool
    kv_transfer_connector_enabled: bool
    ec_transfer_connector_enabled: bool

    def invalid_reasons(self, provenance: SchedulerProvenance) -> tuple[str, ...]:
        checks = {
            "runtime_core_commit": provenance.runtime_core_commit
            == AUDITED_RUNTIME_CORE_COMMIT,
            "device_plugin_commit": provenance.device_plugin_commit
            == AUDITED_DEVICE_PLUGIN_COMMIT,
            "max_concurrent_batches": self.max_concurrent_batches == 1,
            "async_scheduling": self.async_scheduling is False,
            "distributed_executor_backend": self.distributed_executor_backend
            == "uni",
            "tensor_parallel_size": self.tensor_parallel_size == 1,
            "pipeline_parallel_size": self.pipeline_parallel_size == 1,
            "data_parallel_size": self.data_parallel_size == 1,
            "decode_context_parallel_size": self.decode_context_parallel_size == 1,
            "eager_execution": self.eager_execution is True,
            "decoder_only_generation": self.decoder_only_generation is True,
            "multimodal": self.multimodal is False,
            "speculative_decoding": self.speculative_decoding is False,
            "kv_transfer_connector_enabled": (
                self.kv_transfer_connector_enabled is False
            ),
            "ec_transfer_connector_enabled": (
                self.ec_transfer_connector_enabled is False
            ),
        }
        return tuple(name for name, valid in checks.items() if not valid)


@dataclass(slots=True)
class _ConstraintSummary:
    constraint_id: str
    roster: tuple[tuple[str, str], ...]
    counts: dict[tuple[str, str], int] = field(init=False)
    witnesses: dict[tuple[str, str], dict[str, int] | None] = field(init=False)
    evaluated_count: int = 0
    unclassified_count: int = 0
    first_unclassified_witness: dict[str, object] | None = None

    def __post_init__(self) -> None:
        self.counts = {key: 0 for key in self.roster}
        self.witnesses = {key: None for key in self.roster}

    def observe(self, queue: str, mode: str, witness: Mapping[str, int]) -> None:
        ordinal = self.evaluated_count
        self.evaluated_count += 1
        complete = {"evaluation_ordinal": ordinal, **dict(witness)}
        key = (queue, mode)
        if key not in self.counts or any(type(value) is not int for value in complete.values()):
            self.unclassified_count += 1
            if self.first_unclassified_witness is None:
                self.first_unclassified_witness = {
                    **complete,
                    "reason_code": "invalid_observation",
                }
            return
        self.counts[key] += 1
        if self.witnesses[key] is None:
            self.witnesses[key] = complete

    def build(self, not_evaluated_reason: str) -> dict[str, object]:
        accounted = sum(self.counts.values())
        evaluated = self.evaluated_count
        return {
            "constraint_id": self.constraint_id,
            "gate_status": "evaluated" if evaluated else "not_evaluated",
            "not_evaluated_reason": None if evaluated else not_evaluated_reason,
            "evaluated_count": evaluated,
            "accounted_count": accounted,
            "unclassified_count": self.unclassified_count,
            "first_unclassified_witness": self.first_unclassified_witness,
            "buckets": [
                {
                    "queue": queue,
                    "mode": mode,
                    "count": self.counts[(queue, mode)],
                    "first_witness": self.witnesses[(queue, mode)],
                }
                for queue, mode in self.roster
            ],
        }


@dataclass(slots=True)
class SchedulerCycleObservation:
    cycle_start_monotonic_ns: int
    configured_active_sequence_cap: int
    effective_active_sequence_cap: int
    configured_batched_token_budget: int
    effective_batched_token_budget: int
    running_before: int
    waiting_before: int
    token_budget: _ConstraintSummary = field(
        default_factory=lambda: _ConstraintSummary(
            "batched_token_budget", _TOKEN_BUCKETS
        )
    )
    active_sequence_cap: _ConstraintSummary = field(
        default_factory=lambda: _ConstraintSummary(
            "active_sequence_cap", _CAP_BUCKETS
        )
    )

    def observe_token_budget(
        self,
        *,
        queue: str,
        mode: str,
        candidate_tokens: int,
        token_budget_before: int,
        granted_tokens: int,
        running_count: int,
        effective_cap: int,
        waiting_count: int,
    ) -> None:
        self.token_budget.observe(
            queue,
            mode,
            {
                "candidate_tokens_at_gate": candidate_tokens,
                "token_budget_before_at_gate": token_budget_before,
                "granted_tokens_at_budget_gate": granted_tokens,
                "running_count_at_budget_gate": running_count,
                "effective_cap_at_budget_gate": effective_cap,
                "waiting_count_at_budget_gate": waiting_count,
            },
        )

    def observe_active_sequence_cap(
        self,
        *,
        queue: str,
        mode: str,
        waiting_count: int,
        token_budget: int,
        running_count: int,
        effective_cap: int,
    ) -> None:
        self.active_sequence_cap.observe(
            queue,
            mode,
            {
                "cap_gate_waiting_count": waiting_count,
                "token_budget_at_cap_gate": token_budget,
                "running_count_at_cap_gate": running_count,
                "effective_cap_at_gate": effective_cap,
            },
        )


@dataclass(frozen=True, slots=True)
class SchedulerExecutionObservation:
    reference: SchedulerCycleRef
    sampling_status: str


class NullSchedulerProfileRuntime:
    enabled = False

    def __init__(self, invalid_reason: str | None = None) -> None:
        self.invalid_reason = invalid_reason

    def begin_cycle(self, **_fields: int) -> None:
        return None

    def finish_cycle(self, *_args: object, **_kwargs: object) -> None:
        return None

    def begin_execution_step(self, *_args: object, **_kwargs: object) -> None:
        return None

    def finish_execution_step(self, *_args: object, **_kwargs: object) -> bool:
        return False

    def invalidate(self, _reason: str = "runtime_observation_failure") -> None:
        return None

    def close(self) -> None:
        return None


class SchedulerProfileRuntime:
    """Own cycle construction, execution pairing, and bridge sampling."""

    enabled = True

    def __init__(
        self,
        exporter: SchedulerProfileExporter,
        *,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        realtime_ns: Callable[[], int] = time.time_ns,
        start_clock_sampler: bool = True,
    ) -> None:
        self.exporter = exporter
        self._monotonic_ns = monotonic_ns
        self._realtime_ns = realtime_ns
        self._pending: dict[int, SchedulerCycleRef] = {}
        self._pending_lock = threading.Lock()
        self._close_lock = threading.Lock()
        self._close_result: SchedulerCloseResult | None = None
        self._closed = False
        # The exporter is also useful standalone, so it protects itself with
        # an atexit close. Once composed into the runtime, transfer that
        # ownership here so every production close passes through one lock.
        self.exporter._unregister_atexit()
        self._atexit_registered = True
        atexit.register(self.close)
        self._sampler_stop = threading.Event()
        self._sampler: threading.Thread | None = None
        if start_clock_sampler:
            self._sampler = threading.Thread(
                target=self._clock_sampler_main,
                name="rlp-scheduler-clock-bridge",
                daemon=True,
            )
            self._sampler.start()

    def begin_cycle(
        self,
        *,
        configured_active_sequence_cap: int,
        effective_active_sequence_cap: int,
        configured_batched_token_budget: int,
        effective_batched_token_budget: int,
        running_before: int,
        waiting_before: int,
        cycle_start_monotonic_ns: int | None = None,
    ) -> SchedulerCycleObservation | None:
        try:
            return SchedulerCycleObservation(
                cycle_start_monotonic_ns=(
                    self._monotonic_ns()
                    if cycle_start_monotonic_ns is None
                    else cycle_start_monotonic_ns
                ),
                configured_active_sequence_cap=configured_active_sequence_cap,
                effective_active_sequence_cap=effective_active_sequence_cap,
                configured_batched_token_budget=configured_batched_token_budget,
                effective_batched_token_budget=effective_batched_token_budget,
                running_before=running_before,
                waiting_before=waiting_before,
            )
        except Exception:  # noqa: BLE001 - observations never break serving.
            self.invalidate()
            return None

    def finish_cycle(
        self,
        observation: SchedulerCycleObservation | None,
        *,
        output_key: int,
        running_after: int,
        waiting_after: int,
        scheduled_engine_request_count: int,
        scheduled_token_count: int,
        prefill_token_count: int,
        decode_token_count: int,
        cycle_outcome: str = "completed",
        cycle_end_monotonic_ns: int | None = None,
    ) -> SchedulerCycleRef | None:
        if observation is None:
            return None
        try:
            ended = (
                self._monotonic_ns()
                if cycle_end_monotonic_ns is None
                else cycle_end_monotonic_ns
            )
            candidates_before = observation.running_before + observation.waiting_before
            not_evaluated = "no_candidates" if candidates_before == 0 else "gate_not_reached"
            reference = self.exporter.begin_cycle(
                {
                    "cycle_start_monotonic_ns": observation.cycle_start_monotonic_ns,
                    "cycle_end_monotonic_ns": ended,
                    "cycle_outcome": cycle_outcome,
                    "waiting_engine_request_count_before": observation.waiting_before,
                    "running_engine_request_count_before": observation.running_before,
                    "waiting_engine_request_count_after": waiting_after,
                    "running_engine_request_count_after": running_after,
                    "configured_batched_token_budget": (
                        observation.configured_batched_token_budget
                    ),
                    "effective_batched_token_budget": (
                        observation.effective_batched_token_budget
                    ),
                    "configured_active_sequence_cap": (
                        observation.configured_active_sequence_cap
                    ),
                    "effective_active_sequence_cap": (
                        observation.effective_active_sequence_cap
                    ),
                    "token_budget_summary": observation.token_budget.build(
                        not_evaluated
                    ),
                    "active_sequence_cap_summary": (
                        observation.active_sequence_cap.build(not_evaluated)
                    ),
                }
            )
            if reference is None:
                return None
            is_work = scheduled_token_count > 0
            if not self.exporter.write_logical_batch(
                reference,
                {
                    "logical_batch_kind": "work" if is_work else "empty_control",
                    "scheduled_engine_request_count": scheduled_engine_request_count,
                    "scheduled_token_count": scheduled_token_count,
                    "prefill_token_count": prefill_token_count,
                    "decode_token_count": decode_token_count,
                    "runtime_device_relation_candidate_eligible": is_work,
                },
            ):
                return None
            with self._pending_lock:
                self._pending[output_key] = reference
            return reference
        except Exception:  # noqa: BLE001 - observations never break serving.
            self.invalidate()
            return None

    def begin_execution_step(
        self,
        output_key: int,
        *,
        scheduled_token_count: int,
        dispatch_monotonic_ns: int | None = None,
    ) -> SchedulerExecutionObservation | None:
        try:
            with self._pending_lock:
                reference = self._pending.pop(output_key, None)
            if reference is None:
                self.invalidate("execution_pairing_failure")
                return None
            if not self.exporter.write_execution_step_start(
                reference,
                {
                    "dispatch_monotonic_ns": (
                        self._monotonic_ns()
                        if dispatch_monotonic_ns is None
                        else dispatch_monotonic_ns
                    ),
                    "dispatch_kind": "uniproc_execute_model",
                },
            ):
                return None
            return SchedulerExecutionObservation(
                reference,
                "included_in_envelope" if scheduled_token_count > 0 else "not_applicable",
            )
        except Exception:  # noqa: BLE001 - observations never break serving.
            self.invalidate()
            return None

    def finish_execution_step(
        self,
        observation: SchedulerExecutionObservation | None,
        *,
        execution_outcome: str,
        final_result_monotonic_ns: int | None = None,
    ) -> bool:
        if observation is None:
            return False
        try:
            return self.exporter.write_execution_step_end(
                observation.reference,
                {
                    "final_result_monotonic_ns": (
                        self._monotonic_ns()
                        if final_result_monotonic_ns is None
                        else final_result_monotonic_ns
                    ),
                    "execution_outcome": execution_outcome,
                    "sampling_status": observation.sampling_status,
                },
            )
        except Exception:  # noqa: BLE001 - observations never break serving.
            self.invalidate()
            return False

    def invalidate(self, reason: str = "runtime_observation_failure") -> None:
        """Fail formal evidence closed while leaving serving operational."""

        try:
            self.exporter.invalidate_formal_evidence(reason)
        except Exception:
            logger.debug("Scheduler evidence invalidation failed.", exc_info=True)

    def close(self) -> SchedulerCloseResult | None:
        # EngineCore shutdown and interpreter atexit may race in separate
        # threads. Serialize the whole runtime close so a second caller cannot
        # consume the exporter's bounded close deadline and win its immutable
        # completion claim while the first caller is publishing the shard.
        with self._close_lock:
            if self._closed:
                return self._close_result
            self._closed = True
            self._sampler_stop.set()
            if self._sampler is not None:
                self._sampler.join(timeout=1.0)
            try:
                self._close_result = self.exporter.close()
                return self._close_result
            finally:
                if self._atexit_registered:
                    atexit.unregister(self.close)
                    self._atexit_registered = False

    def _clock_sampler_main(self) -> None:
        while not self._sampler_stop.is_set():
            try:
                before = self._monotonic_ns()
                realtime = self._realtime_ns()
                after = self._monotonic_ns()
                if 0 <= after - before <= _CLOCK_BRIDGE_MAX_BRACKET_NS:
                    self.exporter.write_clock_bridge_sample(
                        {
                            "monotonic_before_ns": before,
                            "realtime_ns": realtime,
                            "monotonic_after_ns": after,
                        }
                    )
            except Exception:
                self.invalidate("clock_bridge_observation_failure")
                logger.debug("Scheduler clock bridge sample failed.", exc_info=True)
            self._sampler_stop.wait(1.0)


def create_scheduler_profile_runtime(
    profile: SchedulerRuntimeProfile,
    lifecycle_hooks: RuntimeLifecycleHooks | None = None,
    *,
    env: Mapping[str, str] | None = None,
    start_clock_sampler: bool = True,
) -> SchedulerProfileRuntime | NullSchedulerProfileRuntime:
    """Create the optional runtime adapter without allowing serving failures."""

    source = os.environ if env is None else env
    raw_path = source.get(SCHEDULER_EXPORT_ENV, "").strip()
    if not raw_path:
        return NullSchedulerProfileRuntime()
    try:
        provenance = SchedulerProvenance(
            source.get(TRACE_RUNTIME_COMMIT_ENV, "").strip(),
            source.get(TRACE_DEVICE_COMMIT_ENV, "").strip(),
            source.get(TRACE_PARENT_COMMIT_ENV, "").strip(),
        )
        communication_mode = (
            source.get(TRACE_COMMUNICATION_MODE_ENV, "none").strip() or "none"
        )
        if communication_mode != "none":
            return NullSchedulerProfileRuntime(
                "unsupported_runtime_profile:communication_mode"
            )
        invalid_profile = profile.invalid_reasons(provenance)
        if invalid_profile:
            return NullSchedulerProfileRuntime(
                "unsupported_runtime_profile:" + ",".join(invalid_profile)
            )
        process_instance_id = source.get(TRACE_PROCESS_INSTANCE_ID_ENV, "").strip()
        clock_domain_id = source.get(TRACE_CLOCK_DOMAIN_ID_ENV, "").strip()
        identity = ProcessLocalExporterIdentity(
            process_instance_id,
            clock_domain_id,
            os.getpid(),
        )
        if (
            lifecycle_hooks is not None
            and lifecycle_hooks.enabled
            and (
                lifecycle_hooks.process_uuid != identity.process_instance_id
                or lifecycle_hooks.clock_domain_id != identity.clock_domain_id
            )
        ):
            return NullSchedulerProfileRuntime("lifecycle_identity_mismatch")
        config = SchedulerExporterConfig(
            base_path=Path(raw_path),
            scope=SchedulerShardScope(
                source.get(SCHEDULER_EXPERIMENT_RUN_ID_ENV, "").strip(),
                source.get(SCHEDULER_SERVER_INSTANCE_ID_ENV, "").strip(),
                source.get(SCHEDULER_SHARD_ID_ENV, "").strip(),
            ),
            provenance=provenance,
            runtime_profile_id=SCHEDULER_RUNTIME_PROFILE_ID,
        )
        exporter = create_scheduler_profile_exporter(config, identity)
        if isinstance(exporter, NullSchedulerProfileExporter):
            return NullSchedulerProfileRuntime("exporter_initialization_failure")
        return SchedulerProfileRuntime(
            exporter,
            start_clock_sampler=start_clock_sampler,
        )
    except Exception:
        logger.exception("Scheduler profiler runtime initialization failed.")
        return NullSchedulerProfileRuntime("initialization_failure")
