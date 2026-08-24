from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from vllm_request_lifecycle_profiler.issue19_m0 import (
    SCENARIO_ORDER,
    SEEDS,
    TARGET_KV_CACHE_MEMORY_BYTES,
    TARGET_MAX_MODEL_LEN,
    VersionMetadata,
    build_execution_manifest,
    finalize_readiness,
    inspect_kv_capacity_gate,
    inspect_service_smoke_result,
    inspect_serving_readiness,
    target_configuration,
    write_preflight_outputs,
)
from vllm_request_lifecycle_profiler.oasst1_workload import OASST1_REVISION


def _projection(*, request_count: int = 640) -> dict[str, object]:
    requests = []
    for index in range(request_count):
        repetition = index % 10
        ordinal = index // 10
        requests.append(
            {
                "request_id": f"r{repetition}-{ordinal}",
                "repetition": repetition,
                "ordinal": ordinal,
            }
        )
    return {
        "data_revision": OASST1_REVISION,
        "requests": requests,
    }


def test_execution_manifest_freezes_all_six_paths_and_safety_order() -> None:
    manifest = build_execution_manifest(_projection())

    assert manifest["observer_only"] is True
    assert manifest["lifecycle_reconcile"] is False
    assert manifest["treatment_implemented"] is False
    assert manifest["service_lifecycle_count"] == 10
    assert manifest["communication_mode"] == "issue2:kv-recovery-v1alpha1"
    assert manifest["target"] == target_configuration()
    assert manifest["target"]["max_model_len"] == 10880
    assert manifest["target"]["kv_cache_memory_bytes"] == 2 * 1024**3
    assert [row["seed"] for row in manifest["lifecycles"]] == list(SEEDS)
    for lifecycle in manifest["lifecycles"]:
        assert lifecycle["scenario_order"] == list(SCENARIO_ORDER)
        assert lifecycle["scenario_order"][-1] == "worker_exit"
        assert lifecycle["worker_exit_is_final_action"] is True
        assert len(lifecycle["request_ids"]) == 64
        assert len(lifecycle["unaffected_survivor_request_ids"]) == 58
        assert len(set(lifecycle["scenario_targets"].values())) == 6


def test_execution_manifest_rejects_incomplete_repetition() -> None:
    with pytest.raises(ValueError, match="exact 64-request set"):
        build_execution_manifest(_projection(request_count=630))


def _write_version(repository: Path, release: str) -> None:
    repository.mkdir()
    (repository / "upstream_version.json").write_text(
        json.dumps(
            {
                "release_version": release,
                "upstream_version": f"{release}rc0",
                "upstream_commit": "a" * 40,
            }
        )
    )
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.name", "Test"], check=True
    )


def test_preflight_reports_version_and_general_seam_blockers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "runtime"
    ascend = tmp_path / "ascend"
    _write_version(runtime, "0.23.1")
    _write_version(ascend, "0.19.1")
    (runtime / "vllm/v1").mkdir(parents=True)
    (runtime / "vllm/v1/kv_recovery_profile.py").touch()
    (runtime / "vllm/__init__.py").touch()
    (runtime / "pyproject.toml").write_text(
        '[build-system]\nrequires = ["torch == 2.11.0"]\n'
    )
    (ascend / "vllm_ascend/worker").mkdir(parents=True)
    (ascend / "vllm_ascend/worker/kv_recovery.py").touch()
    (ascend / "vllm_ascend/__init__.py").touch()
    (ascend / "requirements.txt").write_text("torch==2.10.0\ntorch-npu==2.10.0.post4\n")
    (ascend / "docs/source").mkdir(parents=True)
    (ascend / "docs/source/conf.py").write_text(
        'rst_epilog_data = {"pip_vllm_version": "0.19.1"}\n'
    )
    model = tmp_path / "model"
    model.mkdir()
    (model / "config.json").touch()
    (model / "model.safetensors.index.json").touch()
    for index in range(1, 9):
        (model / f"model-{index:05d}-of-00008.safetensors").touch()
    for repository in (runtime, ascend):
        subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(repository), "commit", "-qm", "fixture"], check=True
        )
    monkeypatch.setattr(
        "vllm_request_lifecycle_profiler.issue19_m0.collect_python_environment",
        lambda *_args: {
            "versions": {"vllm": "0.21.0+empty", "torch": "2.10.0"},
            "distributions": {"torch-npu": "2.10.0.post4"},
            "origins": {
                "vllm": str(runtime / "vllm/__init__.py"),
                "vllm_ascend": str(ascend / "vllm_ascend/__init__.py"),
            },
        },
    )
    monkeypatch.setattr(
        "vllm_request_lifecycle_profiler.issue19_m0.probe_source_compatibility",
        lambda *_args: {
            "passed": False,
            "returncode": 1,
            "details": {},
            "stderr_tail": [],
        },
    )
    monkeypatch.setattr(
        "vllm_request_lifecycle_profiler.issue19_m0.probe_ascend_kv_cache_compatibility",
        lambda *_args: {
            "passed": False,
            "returncode": 0,
            "details": {"accepted": False},
            "stderr_tail": [],
        },
    )

    report = inspect_serving_readiness(
        runtime=runtime,
        ascend=ascend,
        runtime_python=Path("python"),
        model_path=model,
    )

    assert report["ready_for_service_smoke"] is False
    assert set(report["blockers"]) >= {
        "pinned_runtime_ascend_version_mismatch",
        "ascend_documented_runtime_mismatch",
        "installed_vllm_carrier_version_mismatch",
        "runtime_ascend_source_import_failed",
        "six_path_general_lifecycle_hook_missing",
        "request_resource_ownership_wiring_missing",
        "ascend_offloading_connector_kv_cache_incompatible",
    }


def test_blocked_output_removes_stale_ready_marker(tmp_path: Path) -> None:
    (tmp_path / "READY.txt").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "READY.txt").write_text("stale")
    write_preflight_outputs(
        tmp_path,
        projection={"requests": []},
        execution={"status": "preflight-only"},
        readiness={"blockers": ["incompatible"]},
    )

    assert not (tmp_path / "READY.txt").exists()
    assert (tmp_path / "BLOCKED.txt").read_text() == (
        "BLOCKED: service smoke was not started.\n- incompatible\n"
    )
    assert (tmp_path / "M0_BLOCKED.txt").read_text() == (
        "M0_BLOCKED: formal M0 must not start.\n- incompatible\n"
    )


def test_preflight_blocks_uncommitted_runtime_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "runtime"
    ascend = tmp_path / "ascend"
    _write_version(runtime, "0.23.0")
    _write_version(ascend, "0.23.0")
    for repository in (runtime, ascend):
        subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(repository), "commit", "-qm", "fixture"], check=True
        )
    (runtime / "uncommitted.py").touch()
    monkeypatch.setattr(
        "vllm_request_lifecycle_profiler.issue19_m0._load_version_metadata",
        lambda _repository: VersionMetadata("0.23.0", "0.23.0rc0", "a" * 40),
    )
    monkeypatch.setattr(
        "vllm_request_lifecycle_profiler.issue19_m0._runtime_torch_requirement",
        lambda _repository: "2.11.0",
    )
    monkeypatch.setattr(
        "vllm_request_lifecycle_profiler.issue19_m0._ascend_torch_requirement",
        lambda _repository: "2.10.0",
    )
    monkeypatch.setattr(
        "vllm_request_lifecycle_profiler.issue19_m0._ascend_torch_npu_requirement",
        lambda _repository: "2.10.0.post4",
    )
    monkeypatch.setattr(
        "vllm_request_lifecycle_profiler.issue19_m0._ascend_documented_vllm_version",
        lambda _repository: "0.23.0",
    )
    monkeypatch.setattr(
        "vllm_request_lifecycle_profiler.issue19_m0.collect_python_environment",
        lambda *_args: {
            "versions": {"vllm": "0.23.0+empty", "torch": "2.10.0"},
            "distributions": {"torch-npu": "2.10.0.post4"},
            "origins": {},
        },
    )
    monkeypatch.setattr(
        "vllm_request_lifecycle_profiler.issue19_m0.probe_source_compatibility",
        lambda *_args: {
            "passed": False,
            "returncode": 1,
            "details": {},
            "stderr_tail": [],
        },
    )
    monkeypatch.setattr(
        "vllm_request_lifecycle_profiler.issue19_m0.probe_ascend_kv_cache_compatibility",
        lambda *_args: {
            "passed": False,
            "returncode": 0,
            "details": {"accepted": False},
            "stderr_tail": [],
        },
    )

    report = inspect_serving_readiness(
        runtime=runtime,
        ascend=ascend,
        runtime_python=Path("python"),
        model_path=tmp_path / "model",
    )

    assert "runtime_worktree_has_uncommitted_changes" in report["blockers"]


def test_kv_capacity_gate_matches_the_corrected_specialty_target(
    tmp_path: Path,
) -> None:
    model = tmp_path / "model"
    model.mkdir()
    (model / "config.json").write_text(
        json.dumps(
            {
                "hidden_size": 5120,
                "num_attention_heads": 40,
                "num_key_value_heads": 8,
                "num_hidden_layers": 48,
                "torch_dtype": "bfloat16",
            }
        )
    )

    corrected = inspect_kv_capacity_gate(model)
    old_target = inspect_kv_capacity_gate(model, max_model_len=32768)

    assert corrected == {
        "passed": True,
        "model_dtype": "bfloat16",
        "bytes_per_token": 196608,
        "block_size": 128,
        "kv_cache_memory_bytes": TARGET_KV_CACHE_MEMORY_BYTES,
        "capacity_tokens": TARGET_MAX_MODEL_LEN,
        "max_model_len": TARGET_MAX_MODEL_LEN,
        "required_bytes": TARGET_KV_CACHE_MEMORY_BYTES - 8 * 1024**2,
    }
    assert old_target["passed"] is False
    assert old_target["required_bytes"] == 6 * 1024**3


def test_service_smoke_result_requires_real_initialization_and_complete_trace(
    tmp_path: Path,
) -> None:
    path = tmp_path / "smoke.json"
    payload = {
        "schema_version": "issue19-service-smoke/v1",
        "evidence_class": "smoke-only",
        "service_started": True,
        "health": {"http_status": 200},
        "connector_initialized": True,
        "resolved_configuration": {**target_configuration(), "port": 18179},
        "trace_validation": {
            "request_terminal_complete": True,
            "recovery_chain_complete": True,
            "dropped_data_count": 0,
            "writer_failure_count": 0,
        },
    }
    path.write_text(json.dumps(payload))

    result = inspect_service_smoke_result(path)

    assert result["passed"] is True
    assert result["initialization_passed"] is True
    assert result["lifecycle_trace_complete"] is True


def test_old_fallback_smoke_cannot_unlock_m0(tmp_path: Path) -> None:
    path = tmp_path / "smoke.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "issue19-service-smoke/v1",
                "evidence_class": "smoke-only",
                "health": {"http_status": 200},
                "resolved_max_model_len": 10880,
                "target_configuration_match": False,
            }
        )
    )
    readiness = {"blockers": []}

    smoke = inspect_service_smoke_result(path)
    finalize_readiness(readiness, smoke)

    assert readiness["ready_for_service_smoke"] is True
    assert readiness["ready_for_m0"] is False
    assert readiness["m0_blockers"] == [
        "service_smoke_initialization_not_verified",
        "service_smoke_lifecycle_trace_incomplete",
    ]


def test_static_preflight_uses_smoke_ready_without_claiming_m0(
    tmp_path: Path,
) -> None:
    readiness = {"blockers": []}
    finalize_readiness(
        readiness,
        {
            "initialization_passed": False,
            "lifecycle_trace_complete": False,
        },
    )

    write_preflight_outputs(
        tmp_path,
        projection={"requests": []},
        execution={"status": "preflight-only"},
        readiness=readiness,
    )

    assert (tmp_path / "SMOKE_READY.txt").is_file()
    assert not (tmp_path / "READY.txt").exists()
    assert (tmp_path / "M0_BLOCKED.txt").is_file()
