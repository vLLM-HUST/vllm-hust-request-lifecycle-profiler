# SPDX-License-Identifier: Apache-2.0
"""Optional Route-B scheduler profiler bridge for the audited vLLM 0.21 path."""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

SCHEDULER_EXPORT_ENV = "VLLM_RLP_SCHEDULER_PROFILE_PATH"


def initialize_scheduler_profile_runtime(
    vllm_config: Any, max_concurrent_batches: int
) -> Any | None:
    if not os.environ.get(SCHEDULER_EXPORT_ENV, "").strip():
        return None
    try:
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
    try:
        from vllm_request_lifecycle_profiler.plugin import (
            close_scheduler_profile_runtime as close_runtime,
        )

        close_runtime()
    except Exception:  # noqa: BLE001 - optional overlay must fail open.
        return
