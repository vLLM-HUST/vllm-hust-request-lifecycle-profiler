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
