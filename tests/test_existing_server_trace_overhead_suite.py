from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_overhead_module():
    path = (
        Path(__file__).resolve().parents[1]
        / ".benchmarks"
        / "run_existing_server_trace_overhead_suite.py"
    )
    spec = importlib.util.spec_from_file_location("run_existing_server_trace_overhead_suite", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_runtime_hook_plan_module():
    path = (
        Path(__file__).resolve().parents[1]
        / ".benchmarks"
        / "run_runtime_hook_pair_plan.py"
    )
    spec = importlib.util.spec_from_file_location("run_runtime_hook_pair_plan", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _profile_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _mode_result(mode: str, *, ttft_p95: float, latency_p95: float, event_count: int):
    return {
        "mode": mode,
        "output_dir": Path(f"/tmp/{mode}"),
        "result": {
            "summary": {
                "request_count": 4,
                "success_count": 4,
                "error_count": 0,
                "event_count": event_count,
                "first_token_ms": {"p50": ttft_p95 / 2, "p95": ttft_p95},
                "latency_ms": {"p50": latency_p95 / 2, "p95": latency_p95},
            }
        },
    }


def test_comparison_reports_trace_overhead_deltas() -> None:
    module = _load_overhead_module()
    comparison = module._comparison(
        [
            _mode_result("no-trace", ttft_p95=80.0, latency_p95=160.0, event_count=0),
            _mode_result("trace", ttft_p95=83.0, latency_p95=166.0, event_count=36),
        ]
    )

    assert comparison["deltas"]["ttft_p95_delta_ms"] == 3.0
    assert comparison["deltas"]["latency_p95_delta_ms"] == 6.0
    assert comparison["deltas"]["event_count_delta"] == 36


def test_runtime_hook_pair_plan_reports_missing_runs(tmp_path: Path) -> None:
    module = _load_runtime_hook_plan_module()
    args = module.parse_args(
        [
            "--hook-disabled-dir",
            str(tmp_path / "disabled"),
            "--hook-enabled-dir",
            str(tmp_path / "enabled"),
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )
    result = module.build_plan(args)

    assert result["summary"]["missing_result_count"] == 2
    assert result["summary"]["rows"][0]["status"] == "missing-result"
    assert "TRACE_SUITE_OUTPUT_DIR=" in result["summary"]["rows"][0][
        "required_next_run"
    ][-1]


def test_npu6_profile_uses_pinned_runtime_and_does_not_enable_hooks_by_default() -> None:
    profile = (
        Path(__file__).resolve().parents[1]
        / ".benchmarks"
        / "profiles"
        / "npu6_vllm_hust_trace.env"
    )
    env = _profile_env(profile)

    assert "VLLM_RLP_TRACE_EXPORT_PATH" not in env
    assert "VLLM_RLP_TRACE_ENABLED" not in env
    assert env["VLLM_OPTIMIZATION_REPO_CONTAINER"] == (
        "/workspace/vllm-request-lifecycle-profiler-plugin"
    )
    assert (
        "/workspace/vllm-request-lifecycle-profiler-plugin/third_party/vllm-hust"
        in env["VLLM_ENGINE_PYTHONPATH"].split(":")
    )


def test_runtime_hook_pair_plan_loads_rows_and_deltas(tmp_path: Path) -> None:
    module = _load_runtime_hook_plan_module()
    disabled_dir = tmp_path / "disabled"
    enabled_dir = tmp_path / "enabled"
    disabled_dir.mkdir()
    enabled_dir.mkdir()
    trace_path = tmp_path / "runtime.jsonl"
    trace_path.write_text(
        '{"request_id":"r1","stage":"scheduled","metadata":{"observer":"vllm_runtime_hook"}}\n'
        '{"request_id":"r1","stage":"first_token","metadata":{"observer":"vllm_runtime_hook"}}\n',
        encoding="utf-8",
    )
    for result_dir, event_count, ttft_p95 in [
        (disabled_dir, 0, 80.0),
        (enabled_dir, 27, 83.5),
    ]:
        (result_dir / "summary.json").write_text(
            json.dumps(
                {
                    "request_count": 3,
                    "success_count": 3,
                    "error_count": 0,
                    "event_count": event_count,
                    "first_token_ms": {"p50": 70.0, "p95": ttft_p95},
                    "latency_ms": {"p50": 150.0, "p95": 170.0},
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (result_dir / "run_metadata.json").write_text(
            json.dumps(
                {
                    "evidence_label": "existing-server-probe",
                    "repo": {
                        "commit": "abc123",
                        "dirty_excluding_output_dir": False,
                    },
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    args = module.parse_args(
        [
            "--hook-disabled-dir",
            str(disabled_dir),
            "--hook-enabled-dir",
            str(enabled_dir),
            "--trace-export-path",
            str(trace_path),
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )
    result = module.build_plan(args)

    assert result["summary"]["loaded_result_count"] == 2
    assert result["summary"]["deltas"]["ttft_p95_delta_ms"] == 3.5
    assert result["summary"]["deltas"]["event_count_delta"] == 27
    assert result["summary"]["rows"][1]["trace_bytes"] == trace_path.stat().st_size
    assert result["summary"]["rows"][1]["source_commit"] == "abc123"
    assert result["summary"]["rows"][1]["source_dirty_excluding_output_dir"] is False
    assert result["summary"]["rows"][1]["runtime_trace_summary"]["event_count"] == 2
    assert result["summary"]["rows"][1]["runtime_trace_summary"]["stage_counts"] == {
        "first_token": 1,
        "scheduled": 1,
    }
