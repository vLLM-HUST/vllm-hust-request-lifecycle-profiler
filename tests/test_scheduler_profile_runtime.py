from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from vllm_request_lifecycle_profiler.runtime_hooks import (
    TRACE_CLOCK_DOMAIN_ID_ENV,
    TRACE_COMMUNICATION_MODE_ENV,
    TRACE_DEVICE_COMMIT_ENV,
    TRACE_EXPORT_ENV,
    TRACE_PARENT_COMMIT_ENV,
    TRACE_PROCESS_INSTANCE_ID_ENV,
    TRACE_RUNTIME_COMMIT_ENV,
    RuntimeLifecycleHooks,
)
from vllm_request_lifecycle_profiler.scheduler_profile_runtime import (
    AUDITED_DEVICE_PLUGIN_COMMIT,
    AUDITED_RUNTIME_CORE_COMMIT,
    SCHEDULER_EXPERIMENT_RUN_ID_ENV,
    SCHEDULER_EXPORT_ENV,
    SCHEDULER_SERVER_INSTANCE_ID_ENV,
    SCHEDULER_SHARD_ID_ENV,
    NullSchedulerProfileRuntime,
    SchedulerProfileRuntime,
    SchedulerRuntimeProfile,
    create_scheduler_profile_runtime,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_SCRIPT = ROOT / "scripts" / "verify_scheduler_profile_contract.py"
PATCH_SCRIPT = ROOT / "scripts" / "apply_scheduler_profile_i2_runtime.py"
HOOK_CARRIER = (
    ROOT / "runtime/vllm_021/vllm/v1/engine/scheduler_profile_hooks.py"
)
PROCESS_ID = "1" * 32
CLOCK_DOMAIN_ID = "a" * 32
PARENT_COMMIT = "b" * 40


def _profile(**overrides: object) -> SchedulerRuntimeProfile:
    values: dict[str, object] = {
        "max_concurrent_batches": 1,
        "async_scheduling": False,
        "distributed_executor_backend": "uni",
        "tensor_parallel_size": 1,
        "pipeline_parallel_size": 1,
        "data_parallel_size": 1,
        "decode_context_parallel_size": 1,
        "eager_execution": True,
        "decoder_only_generation": True,
        "multimodal": False,
        "speculative_decoding": False,
        "kv_transfer_connector_enabled": False,
        "ec_transfer_connector_enabled": False,
    }
    values.update(overrides)
    return SchedulerRuntimeProfile(**values)  # type: ignore[arg-type]


def _env(tmp_path: Path) -> dict[str, str]:
    return {
        SCHEDULER_EXPORT_ENV: str(tmp_path / "scheduler"),
        SCHEDULER_EXPERIMENT_RUN_ID_ENV: "R1",
        SCHEDULER_SERVER_INSTANCE_ID_ENV: "S1",
        SCHEDULER_SHARD_ID_ENV: "SH0",
        TRACE_PROCESS_INSTANCE_ID_ENV: PROCESS_ID,
        TRACE_CLOCK_DOMAIN_ID_ENV: CLOCK_DOMAIN_ID,
        TRACE_PARENT_COMMIT_ENV: PARENT_COMMIT,
        TRACE_RUNTIME_COMMIT_ENV: AUDITED_RUNTIME_CORE_COMMIT,
        TRACE_DEVICE_COMMIT_ENV: AUDITED_DEVICE_PLUGIN_COMMIT,
    }


def _emit_complete_cycle(runtime: SchedulerProfileRuntime) -> None:
    cycle = runtime.begin_cycle(
        configured_active_sequence_cap=512,
        effective_active_sequence_cap=512,
        configured_batched_token_budget=4096,
        effective_batched_token_budget=4096,
        running_before=1,
        waiting_before=1,
    )
    assert cycle is not None
    cycle.observe_active_sequence_cap(
        queue="waiting",
        mode="not_limited",
        waiting_count=1,
        token_budget=4096,
        running_count=1,
        effective_cap=512,
    )
    cycle.observe_token_budget(
        queue="waiting",
        mode="not_limited",
        candidate_tokens=16,
        token_budget_before=4096,
        granted_tokens=16,
        running_count=1,
        effective_cap=512,
        waiting_count=1,
    )
    reference = runtime.finish_cycle(
        cycle,
        output_key=7,
        running_after=2,
        waiting_after=0,
        scheduled_engine_request_count=1,
        scheduled_token_count=16,
        prefill_token_count=12,
        decode_token_count=4,
    )
    assert reference is not None
    execution = runtime.begin_execution_step(7, scheduled_token_count=16)
    assert execution is not None
    assert runtime.finish_execution_step(
        execution, execution_outcome="completed"
    )


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scheduler_runtime_close_is_serialized_and_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = create_scheduler_profile_runtime(
        _profile(), env=_env(tmp_path), start_clock_sampler=False
    )
    assert isinstance(runtime, SchedulerProfileRuntime)
    assert not runtime.exporter._atexit_registered
    assert runtime._atexit_registered
    original_close = runtime.exporter.close
    state_lock = threading.Lock()
    active = 0
    max_active = 0

    def delayed_close():
        nonlocal active, max_active
        with state_lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        try:
            return original_close()
        finally:
            with state_lock:
                active -= 1

    monkeypatch.setattr(runtime.exporter, "close", delayed_close)
    results: list[object] = []
    start = threading.Barrier(3)

    def close_runtime() -> None:
        start.wait()
        results.append(runtime.close())

    threads = [threading.Thread(target=close_runtime) for _ in range(2)]
    for thread in threads:
        thread.start()
    start.wait()
    for thread in threads:
        thread.join()

    assert max_active == 1
    assert len(results) == 2
    assert results[0] is results[1]
    assert results[0] is not None
    assert results[0].writer_complete
    assert not runtime._atexit_registered


def test_scheduler_runtime_is_default_off_without_allocations(tmp_path: Path) -> None:
    runtime = create_scheduler_profile_runtime(
        _profile(), env={}, start_clock_sampler=False
    )

    assert isinstance(runtime, NullSchedulerProfileRuntime)
    assert runtime.invalid_reason is None
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"max_concurrent_batches": 2}, "max_concurrent_batches"),
        ({"async_scheduling": True}, "async_scheduling"),
        ({"distributed_executor_backend": "mp"}, "distributed_executor_backend"),
        ({"speculative_decoding": True}, "speculative_decoding"),
        ({"kv_transfer_connector_enabled": True}, "kv_transfer_connector_enabled"),
    ],
)
def test_unsupported_runtime_profiles_create_no_plausible_shard(
    tmp_path: Path, overrides: dict[str, object], reason: str
) -> None:
    runtime = create_scheduler_profile_runtime(
        _profile(**overrides), env=_env(tmp_path), start_clock_sampler=False
    )

    assert isinstance(runtime, NullSchedulerProfileRuntime)
    assert runtime.invalid_reason is not None and reason in runtime.invalid_reason
    assert list(tmp_path.iterdir()) == []


def test_non_none_lifecycle_communication_mode_creates_no_scheduler_shard(
    tmp_path: Path,
) -> None:
    env = _env(tmp_path) | {
        TRACE_COMMUNICATION_MODE_ENV: "issue2:kv-recovery-v1alpha1"
    }

    runtime = create_scheduler_profile_runtime(
        _profile(), env=env, start_clock_sampler=False
    )

    assert isinstance(runtime, NullSchedulerProfileRuntime)
    assert runtime.invalid_reason == "unsupported_runtime_profile:communication_mode"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "commit_env",
    [TRACE_RUNTIME_COMMIT_ENV, TRACE_DEVICE_COMMIT_ENV],
)
def test_non_audited_source_commits_create_no_scheduler_shard(
    tmp_path: Path, commit_env: str
) -> None:
    env = _env(tmp_path) | {commit_env: "c" * 40}

    runtime = create_scheduler_profile_runtime(
        _profile(), env=env, start_clock_sampler=False
    )

    assert isinstance(runtime, NullSchedulerProfileRuntime)
    assert runtime.invalid_reason is not None
    assert "unsupported_runtime_profile" in runtime.invalid_reason
    assert list(tmp_path.iterdir()) == []


def test_lifecycle_identity_mismatch_creates_no_scheduler_shard(
    tmp_path: Path,
) -> None:
    lifecycle = SimpleNamespace(
        enabled=True,
        process_uuid="2" * 32,
        clock_domain_id=CLOCK_DOMAIN_ID,
    )

    runtime = create_scheduler_profile_runtime(
        _profile(), lifecycle, env=_env(tmp_path), start_clock_sampler=False
    )

    assert isinstance(runtime, NullSchedulerProfileRuntime)
    assert runtime.invalid_reason == "lifecycle_identity_mismatch"
    assert list(tmp_path.iterdir()) == []


def test_i2_runtime_emits_a_c1_valid_cycle_batch_step_shard(tmp_path: Path) -> None:
    runtime = create_scheduler_profile_runtime(
        _profile(), env=_env(tmp_path), start_clock_sampler=False
    )
    assert isinstance(runtime, SchedulerProfileRuntime)

    _emit_complete_cycle(runtime)
    result = runtime.close()

    assert result is not None and result.writer_complete
    shard = runtime.exporter.committed_shard_path
    assert shard is not None
    receipt = tmp_path / "scheduler-validation.json"
    report = json.loads(
        subprocess.check_output(
            [
                sys.executable,
                str(CONTRACT_SCRIPT),
                "--scheduler-shard",
                str(shard),
                "--write-receipt",
                str(receipt),
                "--json",
            ],
            text=True,
        )
    )
    assert report["validation"]["valid"] is True
    rows = [json.loads(line) for line in shard.read_text().splitlines()]
    assert [row["record_type"] for row in rows] == [
        "scheduler_start",
        "schedule_cycle",
        "logical_batch",
        "execution_step_start",
        "execution_step_end",
        "scheduler_summary",
    ]


def test_lifecycle_and_scheduler_use_the_injected_process_identity(
    tmp_path: Path,
) -> None:
    env = _env(tmp_path) | {TRACE_EXPORT_ENV: str(tmp_path / "lifecycle")}
    lifecycle = RuntimeLifecycleHooks.from_env(env)
    assert lifecycle.enabled
    runtime = create_scheduler_profile_runtime(
        _profile(), lifecycle, env=env, start_clock_sampler=False
    )

    assert isinstance(runtime, SchedulerProfileRuntime)
    assert lifecycle.process_uuid == PROCESS_ID
    assert lifecycle.clock_domain_id == CLOCK_DOMAIN_ID
    assert runtime.exporter.identity.process_instance_id == PROCESS_ID
    assert runtime.exporter.identity.clock_domain_id == CLOCK_DOMAIN_ID

    runtime.close()
    lifecycle.close()


def test_runtime_trace_config_rejects_partial_injected_identity(tmp_path: Path) -> None:
    env = _env(tmp_path) | {
        TRACE_EXPORT_ENV: str(tmp_path / "lifecycle"),
    }
    env.pop(TRACE_CLOCK_DOMAIN_ID_ENV)

    hooks = RuntimeLifecycleHooks.from_env(env)

    assert hooks.enabled is False
    assert hooks.shard_path is None


def test_execution_pairing_failure_permanently_rejects_formal_evidence(
    tmp_path: Path,
) -> None:
    runtime = create_scheduler_profile_runtime(
        _profile(), env=_env(tmp_path), start_clock_sampler=False
    )
    assert isinstance(runtime, SchedulerProfileRuntime)

    assert runtime.begin_execution_step(999, scheduled_token_count=1) is None
    result = runtime.close()

    assert result is not None
    assert result.writer_complete is False
    assert result.formal_invalid_reasons == ("execution_pairing_failure",)
    assert runtime.exporter.committed_shard_path is None


def test_audited_hook_carrier_emits_a_complete_runtime_flow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    carrier = _load_module("scheduler_profile_i2_hooks", HOOK_CARRIER)
    runtime = create_scheduler_profile_runtime(
        _profile(), env=_env(tmp_path), start_clock_sampler=False
    )
    assert isinstance(runtime, SchedulerProfileRuntime)
    monkeypatch.setattr(carrier, "get_scheduler_profile_runtime", lambda: runtime)

    waiting = [object()]
    scheduler = SimpleNamespace(
        scheduler_config=SimpleNamespace(
            max_num_seqs=1,
            max_num_batched_tokens=4096,
        ),
        max_num_running_reqs=1,
        max_num_scheduled_tokens=4096,
        running=[object()],
        waiting=waiting,
        skipped_waiting=[],
        _select_waiting_queue_for_scheduling=lambda: waiting,
    )
    observation = carrier.begin_schedule_cycle(scheduler)
    assert observation is not None
    carrier.observe_active_sequence_cap(scheduler, observation, None, 4096)
    carrier.observe_token_budget(
        observation,
        queue="running",
        mode="not_limited",
        candidate_tokens=16,
        token_budget_before=4096,
        granted_tokens=16,
        running_count=1,
        effective_cap=1,
        waiting_count=1,
    )
    token_splits: dict[str, tuple[int, int]] = {}
    carrier.record_token_split(token_splits, "req-0", 16, 12, 0)
    output = SimpleNamespace(
        num_scheduled_tokens={"req-0": 16}, total_num_scheduled_tokens=16
    )
    carrier.finish_schedule_cycle(scheduler, observation, output, token_splits)
    execution = carrier.begin_execution_step(output)
    assert execution is not None
    carrier.finish_execution_step(execution, "completed")

    result = runtime.close()

    assert result is not None and result.writer_complete
    shard = runtime.exporter.committed_shard_path
    assert shard is not None
    receipt = tmp_path / "carrier-scheduler-validation.json"
    report = json.loads(
        subprocess.check_output(
            [
                sys.executable,
                str(CONTRACT_SCRIPT),
                "--scheduler-shard",
                str(shard),
                "--write-receipt",
                str(receipt),
                "--json",
            ],
            text=True,
        )
    )
    assert report["validation"]["valid"] is True
    rows = [json.loads(line) for line in shard.read_text().splitlines()]
    cycle = next(row for row in rows if row["record_type"] == "schedule_cycle")
    assert cycle["active_sequence_cap_summary"]["buckets"][3] == {
        "count": 1,
        "first_witness": {
            "cap_gate_waiting_count": 1,
            "effective_cap_at_gate": 1,
            "evaluation_ordinal": 0,
            "running_count_at_cap_gate": 1,
            "token_budget_at_cap_gate": 4096,
        },
        "mode": "stopped_at_cap",
        "queue": "waiting",
    }


def test_audited_hook_carrier_is_inert_when_default_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    carrier = _load_module("scheduler_profile_i2_hooks_disabled", HOOK_CARRIER)
    monkeypatch.delenv(SCHEDULER_EXPORT_ENV, raising=False)

    assert carrier.get_scheduler_profile_runtime() is None
    assert carrier.begin_schedule_cycle(object()) is None
    carrier.abort_schedule_cycle(None)
    carrier.observe_request_profile(object())
    carrier.record_token_split(None, "req-0", 16, 12, 0)
    carrier.finish_schedule_cycle(object(), None, object(), None)
    assert carrier.begin_execution_step(object()) is None


def test_audited_hook_carrier_invalidates_aborted_and_unsupported_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    carrier = _load_module("scheduler_profile_i2_hooks_invalid", HOOK_CARRIER)
    invalid_reasons: list[str] = []
    runtime = SimpleNamespace(invalidate=invalid_reasons.append)
    monkeypatch.setattr(carrier, "get_scheduler_profile_runtime", lambda: runtime)

    carrier.abort_schedule_cycle(object())
    carrier.observe_request_profile(
        SimpleNamespace(
            trace_headers={"x-vllm-rlp-sampling-n": "1"},
            sampling_params=SimpleNamespace(n=1),
        )
    )
    carrier.observe_request_profile(
        SimpleNamespace(
            trace_headers={"x-vllm-rlp-sampling-n": "2"},
            sampling_params=SimpleNamespace(n=1),
        )
    )

    assert invalid_reasons == [
        "schedule_cycle_aborted",
        "unsupported_runtime_profile:n",
    ]


def test_request_level_n_gt_one_permanently_rejects_formal_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    carrier = _load_module("scheduler_profile_i2_hooks_n_gt_one", HOOK_CARRIER)
    runtime = create_scheduler_profile_runtime(
        _profile(), env=_env(tmp_path), start_clock_sampler=False
    )
    assert isinstance(runtime, SchedulerProfileRuntime)
    monkeypatch.setattr(carrier, "get_scheduler_profile_runtime", lambda: runtime)

    # AsyncLLM carries the original parent n before vLLM fans it out into
    # child requests whose local SamplingParams all have n=1.
    carrier.observe_request_profile(
        SimpleNamespace(
            trace_headers={"x-vllm-rlp-sampling-n": "2"},
            sampling_params=SimpleNamespace(n=1),
        )
    )
    cycle = runtime.begin_cycle(
        configured_active_sequence_cap=1,
        effective_active_sequence_cap=1,
        configured_batched_token_budget=4096,
        effective_batched_token_budget=4096,
        running_before=0,
        waiting_before=1,
    )
    assert cycle is not None
    assert runtime.finish_cycle(
        cycle,
        output_key=99,
        running_after=1,
        waiting_after=0,
        scheduled_engine_request_count=1,
        scheduled_token_count=16,
        prefill_token_count=16,
        decode_token_count=0,
    ) is None

    result = runtime.close()

    assert result is not None
    assert result.writer_complete is False
    assert result.formal_invalid_reasons == ("unsupported_runtime_profile:n",)
    assert runtime.exporter.committed_shard_path is None


def test_i2_patch_carrier_matches_and_compiles_the_audited_runtime() -> None:
    runtime_source = os.environ.get("VLLM_SCHEDULER_I2_SRC", "").strip()
    if not runtime_source:
        pytest.skip("set VLLM_SCHEDULER_I2_SRC to the audited vLLM 0.21 checkout")
    module = _load_module("scheduler_i2_patch", PATCH_SCRIPT)

    outputs = module.build_patched_files(Path(runtime_source))

    assert set(outputs) == {
        module.SCHEDULER_PATH,
        module.CORE_PATH,
        module.ASYNC_LLM_PATH,
        module.HOOK_PATH,
    }
    for relative, payload in outputs.items():
        compile(payload, str(relative), "exec")
    scheduler = outputs[module.SCHEDULER_PATH].decode()
    core = outputs[module.CORE_PATH].decode()
    async_llm = outputs[module.ASYNC_LLM_PATH].decode()
    assert "finish_schedule_cycle(" in scheduler
    assert "observe_active_sequence_cap(" in scheduler
    assert "begin_execution_step(scheduler_output)" in core
    assert "close_scheduler_profile_runtime()" in core
    assert "{} if _rlp_cycle is not None else None" in scheduler
    assert "if _rlp_token_splits is not None:" in scheduler
    assert "abort_schedule_cycle(_rlp_cycle)" in scheduler
    assert "observe_request_profile(request)" in scheduler
    assert "lifecycle_request_admitted(request)" in scheduler
    assert "lifecycle_request_scheduled(request, num_computed_tokens)" in scheduler
    assert "lifecycle_request_finished(request)" in scheduler
    assert "prepare_request_profile_headers(" in async_llm
    assert '"VLLM_RLP_TRACE_EXPORT_PATH"' in async_llm
