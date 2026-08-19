# SPDX-License-Identifier: Apache-2.0
"""Optional Route-B scheduler profiler bridge for the audited vLLM 0.21 path."""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

SCHEDULER_EXPORT_ENV = "VLLM_RLP_SCHEDULER_PROFILE_PATH"
LIFECYCLE_EXPORT_ENV = "VLLM_RLP_TRACE_EXPORT_PATH"
TRACE_ID_HEADER = "x-vllm-rlp-trace-id"
SAMPLING_N_HEADER = "x-vllm-rlp-sampling-n"


class _LifecycleState:
    __slots__ = ("queue_span_id", "scheduled", "trace_id")

    def __init__(self, trace_id: str, queue_span_id: str) -> None:
        self.trace_id = trace_id
        self.queue_span_id = queue_span_id
        self.scheduled = False


_LIFECYCLE_STATES: dict[str, _LifecycleState] = {}


def prepare_request_profile_headers(
    request_id: str,
    trace_headers: Any,
    sampling_n: int,
) -> dict[str, str]:
    """Carry bounded lifecycle identity and scheduler cardinality to EngineCore."""

    headers = dict(trace_headers or ())
    if os.environ.get(LIFECYCLE_EXPORT_ENV, "").strip():
        digest = hashlib.sha256(
            b"rlp.trace/v1alpha1\x00" + request_id.encode("utf-8")
        ).digest()
        headers[TRACE_ID_HEADER] = digest[:16].hex()
    if os.environ.get(SCHEDULER_EXPORT_ENV, "").strip():
        headers[SAMPLING_N_HEADER] = str(sampling_n)
    return headers


def initialize_scheduler_profile_runtime(
    vllm_config: Any, max_concurrent_batches: int
) -> Any | None:
    lifecycle_enabled = bool(
        os.environ.get(LIFECYCLE_EXPORT_ENV, "").strip()
    )
    scheduler_enabled = bool(
        os.environ.get(SCHEDULER_EXPORT_ENV, "").strip()
    )
    if not lifecycle_enabled and not scheduler_enabled:
        return None
    try:
        if lifecycle_enabled:
            from vllm_request_lifecycle_profiler.plugin import (
                initialize_lifecycle_profile_runtime,
            )

            initialize_lifecycle_profile_runtime()
        if not scheduler_enabled:
            return None
        from vllm_request_lifecycle_profiler.plugin import (
            initialize_scheduler_profile_runtime as initialize,
        )
        from vllm_request_lifecycle_profiler.scheduler_profile_runtime import (
            SchedulerRuntimeProfile,
        )

        scheduler = vllm_config.scheduler_config
        parallel = vllm_config.parallel_config
        model = vllm_config.model_config
        profile = SchedulerRuntimeProfile(
            max_concurrent_batches=max_concurrent_batches,
            async_scheduling=bool(scheduler.async_scheduling),
            distributed_executor_backend=str(
                parallel.distributed_executor_backend
            ),
            tensor_parallel_size=parallel.tensor_parallel_size,
            pipeline_parallel_size=parallel.pipeline_parallel_size,
            data_parallel_size=parallel.data_parallel_size,
            decode_context_parallel_size=parallel.decode_context_parallel_size,
            eager_execution=bool(model.enforce_eager),
            decoder_only_generation=(
                not bool(model.is_encoder_decoder)
                and getattr(model, "runner_type", "generate") == "generate"
            ),
            multimodal=bool(getattr(model, "is_multimodal_model", False)),
            speculative_decoding=vllm_config.speculative_config is not None,
            kv_transfer_connector_enabled=vllm_config.kv_transfer_config is not None,
            ec_transfer_connector_enabled=vllm_config.ec_transfer_config is not None,
        )
        return initialize(profile)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover
        logger.warning("Scheduler profiler initialization failed: %s", exc)
        return None


def get_lifecycle_profile_runtime() -> Any | None:
    if not os.environ.get(LIFECYCLE_EXPORT_ENV, "").strip():
        return None
    try:
        from vllm_request_lifecycle_profiler.plugin import (
            get_lifecycle_profile_runtime as get_runtime,
        )

        runtime = get_runtime()
        return runtime if runtime is not None and runtime.enabled else None
    except Exception:  # noqa: BLE001 - optional overlay must fail open.
        return None


def lifecycle_request_admitted(request: Any) -> None:
    runtime = get_lifecycle_profile_runtime()
    if runtime is None or request.request_id in _LIFECYCLE_STATES:
        return
    try:
        trace_id = dict(request.trace_headers or ()).get(TRACE_ID_HEADER)
        if (
            not isinstance(trace_id, str)
            or len(trace_id) != 32
            or any(char not in "0123456789abcdef" for char in trace_id)
        ):
            return
        span_id = runtime.new_span_id()
        if span_id is None:
            return
        from vllm_request_lifecycle_profiler.runtime_protocol import EventDraft

        emitted = runtime.emit_event(
            EventDraft(
                trace_id=trace_id,
                lifecycle_id=f"{trace_id}:e:0",
                parent_lifecycle_id=f"{trace_id}:r",
                scope="engine_sample",
                component="engine_client",
                event_name="queued",
                preemption_epoch=0,
                sample_index=0,
                start_span_id=span_id,
            )
        )
        if emitted is not None:
            _LIFECYCLE_STATES[request.request_id] = _LifecycleState(
                trace_id=trace_id,
                queue_span_id=span_id,
            )
    except Exception:  # noqa: BLE001 - optional overlay must fail open.
        return


def lifecycle_request_scheduled(request: Any, computed_tokens_before: int) -> None:
    runtime = get_lifecycle_profile_runtime()
    state = _LIFECYCLE_STATES.get(request.request_id)
    if runtime is None or state is None or state.scheduled:
        return
    try:
        from vllm_request_lifecycle_profiler.runtime_protocol import EventDraft

        prompt_tokens = int(request.num_prompt_tokens)
        cached_tokens = int(computed_tokens_before)
        emitted = runtime.emit_event(
            EventDraft(
                trace_id=state.trace_id,
                lifecycle_id=f"{state.trace_id}:e:0",
                parent_lifecycle_id=f"{state.trace_id}:r",
                scope="engine_sample",
                component="engine_core",
                event_name="scheduled",
                preemption_epoch=int(request.num_preemptions),
                sample_index=0,
                end_span_id=state.queue_span_id,
                metadata={
                    "prompt_tokens_total": prompt_tokens,
                    "prompt_tokens_cached": cached_tokens,
                    "prompt_tokens_to_compute": prompt_tokens - cached_tokens,
                },
            )
        )
        if emitted is not None:
            state.scheduled = True
    except Exception:  # noqa: BLE001 - optional overlay must fail open.
        return


def lifecycle_request_finished(request: Any) -> None:
    runtime = get_lifecycle_profile_runtime()
    state = _LIFECYCLE_STATES.pop(request.request_id, None)
    if runtime is None or state is None:
        return
    try:
        from vllm_request_lifecycle_profiler.runtime_protocol import EventDraft

        common = {
            "trace_id": state.trace_id,
            "lifecycle_id": f"{state.trace_id}:e:0",
            "parent_lifecycle_id": f"{state.trace_id}:r",
            "scope": "engine_sample",
            "component": "engine_core",
            "preemption_epoch": int(request.num_preemptions),
            "sample_index": 0,
        }
        generated_tokens = int(request.num_output_tokens)
        if state.scheduled and generated_tokens > 0:
            runtime.emit_event(
                EventDraft(
                    **common,
                    event_name="generation_done",
                    metadata={"generated_tokens_total": generated_tokens},
                )
            )
        else:
            runtime.emit_event(
                EventDraft(
                    **common,
                    event_name="aborted",
                    closing_span_ids=(
                        () if state.scheduled else (state.queue_span_id,)
                    ),
                )
            )
        cleanup_span_id = runtime.new_span_id()
        if cleanup_span_id is None:
            return
        cleanup_metadata = {"cleanup_component": "engine_request"}
        runtime.emit_event(
            EventDraft(
                **common,
                event_name="cleanup_started",
                start_span_id=cleanup_span_id,
                metadata=cleanup_metadata,
            )
        )
        runtime.emit_event(
            EventDraft(
                **common,
                event_name="cleanup_done",
                end_span_id=cleanup_span_id,
                metadata=cleanup_metadata,
            )
        )
    except Exception:  # noqa: BLE001 - optional overlay must fail open.
        return


def get_scheduler_profile_runtime() -> Any | None:
    if not os.environ.get(SCHEDULER_EXPORT_ENV, "").strip():
        return None
    try:
        from vllm_request_lifecycle_profiler.plugin import (
            get_scheduler_profile_runtime as get_runtime,
        )

        return get_runtime()
    except Exception:  # noqa: BLE001 - optional overlay must fail open.
        return None


def begin_schedule_cycle(scheduler: Any) -> Any | None:
    runtime = get_scheduler_profile_runtime()
    if runtime is None:
        return None
    try:
        return runtime.begin_cycle(
            configured_active_sequence_cap=scheduler.scheduler_config.max_num_seqs,
            effective_active_sequence_cap=scheduler.max_num_running_reqs,
            configured_batched_token_budget=(
                scheduler.scheduler_config.max_num_batched_tokens
            ),
            effective_batched_token_budget=scheduler.max_num_scheduled_tokens,
            running_before=len(scheduler.running),
            waiting_before=len(scheduler.waiting) + len(scheduler.skipped_waiting),
        )
    except Exception:  # noqa: BLE001 - optional overlay must fail open.
        runtime.invalidate("runtime_hook_failure")
        return None


def abort_schedule_cycle(observation: Any | None) -> None:
    runtime = get_scheduler_profile_runtime()
    if runtime is None or observation is None:
        return
    try:
        runtime.invalidate("schedule_cycle_aborted")
    except Exception:  # noqa: BLE001 - optional overlay must fail open.
        return


def observe_request_profile(request: Any) -> None:
    runtime = get_scheduler_profile_runtime()
    if runtime is None:
        return
    try:
        headers = request.trace_headers or {}
        sampling_n = headers.get(SAMPLING_N_HEADER)
        request_n = getattr(request.sampling_params, "n", None)
        if sampling_n != "1" or request_n != 1:
            runtime.invalidate("unsupported_runtime_profile:n")
    except Exception:  # noqa: BLE001 - optional overlay must fail open.
        runtime.invalidate("runtime_hook_failure")
        return


def waiting_queue_name(scheduler: Any, request_queue: Any) -> str:
    return (
        "skipped_waiting"
        if request_queue is scheduler.skipped_waiting
        else "waiting"
    )


def observe_token_budget(
    observation: Any | None,
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
    if observation is None:
        return
    try:
        observation.observe_token_budget(
            queue=queue,
            mode=mode,
            candidate_tokens=candidate_tokens,
            token_budget_before=token_budget_before,
            granted_tokens=granted_tokens,
            running_count=running_count,
            effective_cap=effective_cap,
            waiting_count=waiting_count,
        )
    except Exception:  # noqa: BLE001 - optional overlay must fail open.
        runtime = get_scheduler_profile_runtime()
        if runtime is not None:
            runtime.invalidate("runtime_hook_failure")
        return


def observe_active_sequence_cap(
    scheduler: Any,
    observation: Any | None,
    request_queue: Any,
    token_budget: int,
) -> None:
    if observation is None:
        return
    try:
        if request_queue is None:
            request_queue = scheduler._select_waiting_queue_for_scheduling()
        if request_queue is None:
            raise RuntimeError("active-cap gate has no waiting queue")
        running_count = len(scheduler.running)
        observation.observe_active_sequence_cap(
            queue=waiting_queue_name(scheduler, request_queue),
            mode=(
                "stopped_at_cap"
                if running_count == scheduler.max_num_running_reqs
                else "not_limited"
            ),
            waiting_count=len(scheduler.waiting) + len(scheduler.skipped_waiting),
            token_budget=token_budget,
            running_count=running_count,
            effective_cap=scheduler.max_num_running_reqs,
        )
    except Exception:  # noqa: BLE001 - optional overlay must fail open.
        runtime = get_scheduler_profile_runtime()
        if runtime is not None:
            runtime.invalidate("runtime_hook_failure")
        return


def record_token_split(
    token_splits: dict[str, tuple[int, int]] | None,
    request_id: str,
    scheduled_tokens: int,
    prompt_tokens: int,
    computed_tokens_before: int,
) -> None:
    if token_splits is None:
        return
    prefill = min(
        scheduled_tokens,
        max(0, prompt_tokens - computed_tokens_before),
    )
    token_splits[request_id] = (prefill, scheduled_tokens - prefill)


def finish_schedule_cycle(
    scheduler: Any,
    observation: Any | None,
    scheduler_output: Any,
    token_splits: dict[str, tuple[int, int]] | None,
) -> None:
    runtime = get_scheduler_profile_runtime()
    if runtime is None or observation is None:
        return
    try:
        if token_splits is None:
            raise RuntimeError("enabled cycle is missing token split storage")
        retained = [
            token_splits[request_id]
            for request_id in scheduler_output.num_scheduled_tokens
        ]
        runtime.finish_cycle(
            observation,
            output_key=id(scheduler_output),
            running_after=len(scheduler.running),
            waiting_after=len(scheduler.waiting) + len(scheduler.skipped_waiting),
            scheduled_engine_request_count=len(
                scheduler_output.num_scheduled_tokens
            ),
            scheduled_token_count=scheduler_output.total_num_scheduled_tokens,
            prefill_token_count=sum(item[0] for item in retained),
            decode_token_count=sum(item[1] for item in retained),
        )
    except Exception:  # noqa: BLE001 - optional overlay must fail open.
        runtime.invalidate("runtime_hook_failure")
        return


def begin_execution_step(scheduler_output: Any) -> Any | None:
    runtime = get_scheduler_profile_runtime()
    if runtime is None:
        return None
    try:
        return runtime.begin_execution_step(
            id(scheduler_output),
            scheduled_token_count=scheduler_output.total_num_scheduled_tokens,
        )
    except Exception:  # noqa: BLE001 - optional overlay must fail open.
        runtime.invalidate("runtime_hook_failure")
        return None


def finish_execution_step(observation: Any | None, outcome: str) -> None:
    runtime = get_scheduler_profile_runtime()
    if runtime is None:
        return
    try:
        runtime.finish_execution_step(observation, execution_outcome=outcome)
    except Exception:  # noqa: BLE001 - optional overlay must fail open.
        runtime.invalidate("runtime_hook_failure")
        return


def close_scheduler_profile_runtime() -> None:
    _LIFECYCLE_STATES.clear()
    try:
        from vllm_request_lifecycle_profiler.plugin import (
            close_scheduler_profile_runtime as close_runtime,
        )

        close_runtime()
    except Exception:
        logger.debug("Scheduler profiler close failed.", exc_info=True)
    try:
        from vllm_request_lifecycle_profiler.plugin import (
            close_lifecycle_profile_runtime,
        )

        close_lifecycle_profile_runtime()
    except Exception:  # noqa: BLE001 - optional overlay must fail open.
        return
