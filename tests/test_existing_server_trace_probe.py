from __future__ import annotations

import importlib.util
from pathlib import Path

from vllm_request_lifecycle_profiler.trace import LifecycleStage


def _load_probe_module():
    path = Path(__file__).resolve().parents[1] / ".benchmarks" / "run_existing_server_trace_probe.py"
    spec = importlib.util.spec_from_file_location("run_existing_server_trace_probe", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_event_matches_preflight_trace_schema() -> None:
    module = _load_probe_module()
    event = module._event(
        request_id="req-1",
        stage=LifecycleStage.FIRST_TOKEN,
        timestamp_ms=12.5,
        metadata={"observer": "client_probe"},
    )
    assert event["request_id"] == "req-1"
    assert event["stage"] == "first_token"
    assert event["timestamp_ms"] == 12.5
    assert event["metadata"]["observer"] == "client_probe"


def test_numeric_summary_reports_tail_percentiles() -> None:
    module = _load_probe_module()
    summary = module._numeric_summary([1.0, 2.0, 3.0, 100.0])
    assert summary["count"] == 4
    assert summary["min"] == 1.0
    assert summary["p50"] == 2.5
    assert summary["p95"] > 80.0
    assert summary["p99"] > summary["p95"]
    assert summary["max"] == 100.0


def test_parse_args_supports_no_trace_mode() -> None:
    module = _load_probe_module()
    args = module.parse_args(["--observer-mode", "no-trace"])
    assert args.observer_mode == "no-trace"


def test_parse_args_supports_streaming_proxy_delay() -> None:
    module = _load_probe_module()
    args = module.parse_args(
        [
            "--per-chunk-read-delay-ms",
            "80",
            "--proxy-stage-mode",
            "streaming-proxy",
        ]
    )
    assert args.per_chunk_read_delay_ms == 80
    assert args.proxy_stage_mode == "streaming-proxy"
