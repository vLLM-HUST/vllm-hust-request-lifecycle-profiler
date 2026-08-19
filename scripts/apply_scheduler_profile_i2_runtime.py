#!/usr/bin/env python3
"""Apply the I2 thin-hook carrier to the audited vLLM 0.21 source tree."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEDULER_PATH = Path("vllm/v1/core/sched/scheduler.py")
CORE_PATH = Path("vllm/v1/engine/core.py")
ASYNC_LLM_PATH = Path("vllm/v1/engine/async_llm.py")
HOOK_PATH = Path("vllm/v1/engine/scheduler_profile_hooks.py")
HOOK_SOURCE = ROOT / "runtime" / "vllm_021" / HOOK_PATH

EXPECTED_SHA256 = {
    SCHEDULER_PATH: "4145257a7ecaf921026cf76d61d615c366d2cabcff9cb826a4c1ce32001edfa4",
    CORE_PATH: "53ff4df24745e3ac4ac09028ddeb310f6627b90f6374dbfa82548e97c9bc65bc",
    ASYNC_LLM_PATH: "e629481e82e99967a2aaf7a7384bd2df6b3d758d218a5589ebfe00ce2cb696d2",
}


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    if source.count(old) != 1:
        raise ValueError(f"I2 runtime anchor {label} matched {source.count(old)} times")
    return source.replace(old, new, 1)


def _guard_schedule_exceptions(source: str) -> str:
    header = "    def schedule(self) -> SchedulerOutput:\n"
    boundary = "    def _build_kv_connector_meta(\n"
    if source.count(header) != 1 or source.count(boundary) != 1:
        raise ValueError("I2 runtime schedule exception boundary is ambiguous")
    body_start = source.index(header) + len(header)
    body_end = source.index(boundary, body_start)
    body = source[body_start:body_end]
    guarded_body = "".join(
        f"    {line}" if line.strip() else line
        for line in body.splitlines(keepends=True)
    )
    return (
        source[:body_start]
        + "        _rlp_cycle = begin_schedule_cycle(self)\n"
        + "        try:\n"
        + guarded_body
        + "        except BaseException:\n"
        + "            abort_schedule_cycle(_rlp_cycle)\n"
        + "            raise\n\n"
        + source[body_end:]
    )


def patch_scheduler(source: str) -> str:
    source = _replace_once(
        source,
        "from vllm.v1.engine import EngineCoreEventType, EngineCoreOutput, EngineCoreOutputs\n",
        "from vllm.v1.engine import EngineCoreEventType, EngineCoreOutput, EngineCoreOutputs\n"
        "from vllm.v1.engine.scheduler_profile_hooks import (\n"
        "    abort_schedule_cycle,\n"
        "    begin_schedule_cycle,\n"
        "    finish_schedule_cycle,\n"
        "    lifecycle_request_admitted,\n"
        "    lifecycle_request_finished,\n"
        "    lifecycle_request_scheduled,\n"
        "    observe_active_sequence_cap,\n"
        "    observe_request_profile,\n"
        "    observe_token_budget,\n"
        "    record_token_split,\n"
        ")\n",
        "scheduler_import",
    )
    source = _replace_once(
        source,
        "        scheduled_new_reqs: list[Request] = []\n",
        "        _rlp_token_splits: dict[str, tuple[int, int]] | None = (\n"
        "            {} if _rlp_cycle is not None else None\n"
        "        )\n\n"
        "        scheduled_new_reqs: list[Request] = []\n",
        "cycle_begin",
    )
    source = _replace_once(
        source,
        "            num_new_tokens = min(num_new_tokens, token_budget)\n\n"
        "            # Make sure the input position does not exceed the max model len.\n",
        "            _rlp_candidate_tokens = num_new_tokens\n"
        "            _rlp_granted_tokens = min(num_new_tokens, token_budget)\n"
        "            observe_token_budget(\n"
        "                _rlp_cycle,\n"
        "                queue=\"running\",\n"
        "                mode=(\"clipped\" if num_new_tokens > token_budget "
        "else \"not_limited\"),\n"
        "                candidate_tokens=_rlp_candidate_tokens,\n"
        "                token_budget_before=token_budget,\n"
        "                granted_tokens=_rlp_granted_tokens,\n"
        "                running_count=len(self.running),\n"
        "                effective_cap=self.max_num_running_reqs,\n"
        "                waiting_count=len(self.waiting) + len(self.skipped_waiting),\n"
        "            )\n"
        "            num_new_tokens = _rlp_granted_tokens\n\n"
        "            # Make sure the input position does not exceed the max model len.\n",
        "running_budget",
    )
    source = _replace_once(
        source,
        "                            token_budget += num_scheduled_tokens.pop(preempted_req_id)\n"
        "                            req_to_new_blocks.pop(preempted_req_id)\n",
        "                            token_budget += num_scheduled_tokens.pop(preempted_req_id)\n"
        "                            if _rlp_token_splits is not None:\n"
        "                                _rlp_token_splits.pop(\n"
        "                                    preempted_req_id, None\n"
        "                                )\n"
        "                            req_to_new_blocks.pop(preempted_req_id)\n",
        "preempted_split",
    )
    source = _replace_once(
        source,
        "            num_scheduled_tokens[request_id] = num_new_tokens\n"
        "            token_budget -= num_new_tokens\n"
        "            req_index += 1\n",
        "            num_scheduled_tokens[request_id] = num_new_tokens\n"
        "            record_token_split(\n"
        "                _rlp_token_splits, request_id, num_new_tokens,\n"
        "                request.num_prompt_tokens, request.num_computed_tokens,\n"
        "            )\n"
        "            token_budget -= num_new_tokens\n"
        "            req_index += 1\n",
        "running_token_split",
    )
    source = _replace_once(
        source,
        "            while (self.waiting or self.skipped_waiting) and token_budget > 0:\n"
        "                if len(self.running) == self.max_num_running_reqs:\n"
        "                    break\n\n"
        "                request_queue = self._select_waiting_queue_for_scheduling()\n",
        "            while (self.waiting or self.skipped_waiting) and token_budget > 0:\n"
        "                if len(self.running) == self.max_num_running_reqs:\n"
        "                    observe_active_sequence_cap(\n"
        "                        self, _rlp_cycle, None, token_budget\n"
        "                    )\n"
        "                    break\n\n"
        "                request_queue = self._select_waiting_queue_for_scheduling()\n"
        "                observe_active_sequence_cap(\n"
        "                    self, _rlp_cycle, request_queue, token_budget\n"
        "                )\n\n",
        "active_cap_gate",
    )
    source = _replace_once(
        source,
        "                    if (\n"
        "                        not self.scheduler_config.enable_chunked_prefill\n"
        "                        and num_new_tokens > token_budget\n"
        "                    ):\n"
        "                        # If chunked_prefill is disabled,\n"
        "                        # we can stop the scheduling here.\n"
        "                        break\n\n"
        "                    num_new_tokens = min(num_new_tokens, token_budget)\n",
        "                    if (\n"
        "                        not self.scheduler_config.enable_chunked_prefill\n"
        "                        and num_new_tokens > token_budget\n"
        "                    ):\n"
        "                        observe_token_budget(\n"
        "                            _rlp_cycle,\n"
        "                            queue=(\"skipped_waiting\" if request_queue "
        "is self.skipped_waiting else \"waiting\"),\n"
        "                            mode=\"stopped_no_chunk\",\n"
        "                            candidate_tokens=num_new_tokens,\n"
        "                            token_budget_before=token_budget,\n"
        "                            granted_tokens=0,\n"
        "                            running_count=len(self.running),\n"
        "                            effective_cap=self.max_num_running_reqs,\n"
        "                            waiting_count=(len(self.waiting) + "
        "len(self.skipped_waiting)),\n"
        "                        )\n"
        "                        # If chunked_prefill is disabled,\n"
        "                        # we can stop the scheduling here.\n"
        "                        break\n\n"
        "                    _rlp_candidate_tokens = num_new_tokens\n"
        "                    _rlp_granted_tokens = min(num_new_tokens, token_budget)\n"
        "                    observe_token_budget(\n"
        "                        _rlp_cycle,\n"
        "                        queue=(\"skipped_waiting\" if request_queue "
        "is self.skipped_waiting else \"waiting\"),\n"
        "                        mode=(\"clipped\" if num_new_tokens > token_budget "
        "else \"not_limited\"),\n"
        "                        candidate_tokens=_rlp_candidate_tokens,\n"
        "                        token_budget_before=token_budget,\n"
        "                        granted_tokens=_rlp_granted_tokens,\n"
        "                        running_count=len(self.running),\n"
        "                        effective_cap=self.max_num_running_reqs,\n"
        "                        waiting_count=(len(self.waiting) + "
        "len(self.skipped_waiting)),\n"
        "                    )\n"
        "                    num_new_tokens = _rlp_granted_tokens\n",
        "waiting_budget",
    )
    source = _replace_once(
        source,
        "                num_scheduled_tokens[request_id] = num_new_tokens\n"
        "                token_budget -= num_new_tokens\n"
        "                request.status = RequestStatus.RUNNING\n",
        "                num_scheduled_tokens[request_id] = num_new_tokens\n"
        "                record_token_split(\n"
        "                    _rlp_token_splits, request_id, num_new_tokens,\n"
        "                    request.num_prompt_tokens, num_computed_tokens,\n"
        "                )\n"
        "                token_budget -= num_new_tokens\n"
        "                request.status = RequestStatus.RUNNING\n"
        "                lifecycle_request_scheduled(request, num_computed_tokens)\n",
        "waiting_token_split",
    )
    source = _replace_once(
        source,
        "        with record_function_or_nullcontext(\"schedule: update_after_schedule\"):\n"
        "            self._update_after_schedule(scheduler_output)\n"
        "        return scheduler_output\n",
        "        with record_function_or_nullcontext(\"schedule: update_after_schedule\"):\n"
        "            self._update_after_schedule(scheduler_output)\n"
        "        finish_schedule_cycle(\n"
        "            self, _rlp_cycle, scheduler_output, _rlp_token_splits\n"
        "        )\n"
        "        return scheduler_output\n",
        "cycle_finish",
    )
    source = _replace_once(
        source,
        "        else:\n"
        "            if request.resumable:\n",
        "        else:\n"
        "            observe_request_profile(request)\n"
        "            lifecycle_request_admitted(request)\n"
        "            if request.resumable:\n",
        "request_profile",
    )
    source = _replace_once(
        source,
        "        assert request.is_finished()\n\n"
        "        connector_delay_free_blocks, kv_xfer_params = self._connector_finished(request)\n",
        "        assert request.is_finished()\n"
        "        lifecycle_request_finished(request)\n\n"
        "        connector_delay_free_blocks, kv_xfer_params = self._connector_finished(request)\n",
        "lifecycle_finish",
    )
    return _guard_schedule_exceptions(source)


def patch_async_llm(source: str) -> str:
    source = _replace_once(
        source,
        "from vllm.v1.engine.output_processor import OutputProcessor, RequestOutputCollector\n",
        "from vllm.v1.engine.output_processor import OutputProcessor, RequestOutputCollector\n"
        "from vllm.v1.engine.scheduler_profile_hooks import (\n"
        "    prepare_request_profile_headers,\n"
        ")\n",
        "request_profile_import",
    )
    return _replace_once(
        source,
        "        # Use cloned params that may have been updated in process_inputs()\n"
        "        params = request.params\n\n"
        "        if is_pooling or params.n == 1:\n",
        "        # Use cloned params that may have been updated in process_inputs()\n"
        "        params = request.params\n"
        "        if (\n"
        "            os.environ.get(\"VLLM_RLP_TRACE_EXPORT_PATH\", \"\").strip()\n"
        "            or os.environ.get(\n"
        "                \"VLLM_RLP_SCHEDULER_PROFILE_PATH\", \"\"\n"
        "            ).strip()\n"
        "        ):\n"
        "            request.trace_headers = prepare_request_profile_headers(\n"
        "                request.request_id,\n"
        "                request.trace_headers,\n"
        "                1 if is_pooling else params.n,\n"
        "            )\n"
        "\n"
        "        if is_pooling or params.n == 1:\n",
        "request_sampling_n",
    )


def patch_core(source: str) -> str:
    source = _replace_once(
        source,
        "from vllm.v1.engine.tensor_ipc import TensorIpcReceiver\n",
        "from vllm.v1.engine.scheduler_profile_hooks import (\n"
        "    begin_execution_step,\n"
        "    close_scheduler_profile_runtime,\n"
        "    finish_execution_step,\n"
        "    initialize_scheduler_profile_runtime,\n"
        ")\n"
        "from vllm.v1.engine.tensor_ipc import TensorIpcReceiver\n",
        "core_import",
    )
    source = _replace_once(
        source,
        "        if self.batch_queue_size > 1:\n"
        "            logger.debug(\"Batch queue is enabled with size %d\", "
        "self.batch_queue_size)\n"
        "            self.batch_queue = deque(maxlen=self.batch_queue_size)\n\n"
        "        self.is_ec_consumer = (\n",
        "        if self.batch_queue_size > 1:\n"
        "            logger.debug(\"Batch queue is enabled with size %d\", "
        "self.batch_queue_size)\n"
        "            self.batch_queue = deque(maxlen=self.batch_queue_size)\n\n"
        "        initialize_scheduler_profile_runtime(\n"
        "            vllm_config, self.batch_queue_size\n"
        "        )\n\n"
        "        self.is_ec_consumer = (\n",
        "runtime_initialize",
    )
    source = _replace_once(
        source,
        "        scheduler_output = self.scheduler.schedule()\n"
        "        future = self.model_executor.execute_model(scheduler_output, non_block=True)\n"
        "        grammar_output = self.scheduler.get_grammar_bitmask(scheduler_output)\n"
        "        with (\n"
        "            self.log_error_detail(scheduler_output),\n"
        "            self.log_iteration_details(scheduler_output),\n"
        "        ):\n"
        "            model_output = future.result()\n"
        "            if model_output is None:\n"
        "                model_output = self.model_executor.sample_tokens(grammar_output)\n",
        "        scheduler_output = self.scheduler.schedule()\n"
        "        _rlp_execution = begin_execution_step(scheduler_output)\n"
        "        try:\n"
        "            future = self.model_executor.execute_model(\n"
        "                scheduler_output, non_block=True\n"
        "            )\n"
        "            grammar_output = self.scheduler.get_grammar_bitmask(\n"
        "                scheduler_output\n"
        "            )\n"
        "            with (\n"
        "                self.log_error_detail(scheduler_output),\n"
        "                self.log_iteration_details(scheduler_output),\n"
        "            ):\n"
        "                model_output = future.result()\n"
        "                if model_output is None:\n"
        "                    model_output = self.model_executor.sample_tokens(\n"
        "                        grammar_output\n"
        "                    )\n"
        "        except BaseException:\n"
        "            finish_execution_step(_rlp_execution, \"failed\")\n"
        "            raise\n"
        "        finish_execution_step(_rlp_execution, \"completed\")\n",
        "sync_execution",
    )
    return _replace_once(
        source,
        "    def shutdown(self):\n"
        "        self.structured_output_manager.clear_backend()\n",
        "    def shutdown(self):\n"
        "        close_scheduler_profile_runtime()\n"
        "        self.structured_output_manager.clear_backend()\n",
        "runtime_close",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_patched_files(runtime_source: Path) -> dict[Path, bytes]:
    outputs: dict[Path, bytes] = {}
    for relative, expected in EXPECTED_SHA256.items():
        path = runtime_source / relative
        if _sha256(path) != expected:
            raise ValueError(f"audited source mismatch: {relative}")
    outputs[SCHEDULER_PATH] = patch_scheduler(
        (runtime_source / SCHEDULER_PATH).read_text(encoding="utf-8")
    ).encode()
    outputs[CORE_PATH] = patch_core(
        (runtime_source / CORE_PATH).read_text(encoding="utf-8")
    ).encode()
    outputs[ASYNC_LLM_PATH] = patch_async_llm(
        (runtime_source / ASYNC_LLM_PATH).read_text(encoding="utf-8")
    ).encode()
    outputs[HOOK_PATH] = HOOK_SOURCE.read_bytes()
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-source", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    outputs = build_patched_files(args.runtime_source)
    if args.apply:
        for relative, payload in outputs.items():
            path = args.runtime_source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
    for relative, payload in outputs.items():
        print(f"{hashlib.sha256(payload).hexdigest()}  {relative}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
