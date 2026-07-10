from __future__ import annotations

import importlib.util
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
