from __future__ import annotations

import importlib.util
from pathlib import Path

from vllm_request_lifecycle_profiler.trace import LifecycleStage
from vllm_request_lifecycle_profiler.trace import TraceEvent


def _load_diagnosis_module():
    path = (
        Path(__file__).resolve().parents[1]
        / ".benchmarks"
        / "analyze_trace_diagnosis.py"
    )
    spec = importlib.util.spec_from_file_location("analyze_trace_diagnosis", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_trace_diagnosis_reports_client_visible_dominant_span() -> None:
    module = _load_diagnosis_module()
    events = (
        TraceEvent("req::warmup::0", LifecycleStage.RECEIVED, 0.0),
        TraceEvent("req::warmup::0", LifecycleStage.TOKENIZED, 1.0),
        TraceEvent("req::warmup::0", LifecycleStage.QUEUED, 1.1),
        TraceEvent("req::warmup::0", LifecycleStage.SCHEDULED, 2.0),
        TraceEvent("req::warmup::0", LifecycleStage.PREFILL_DONE, 6.0),
        TraceEvent("req::warmup::0", LifecycleStage.FIRST_TOKEN, 6.0),
        TraceEvent("req::warmup::0", LifecycleStage.DECODE_DONE, 16.0),
        TraceEvent("req::warmup::0", LifecycleStage.STREAM_DONE, 16.0),
        TraceEvent("req::warmup::0", LifecycleStage.CLEANUP_DONE, 17.0),
        TraceEvent("req::repeat0::0", LifecycleStage.RECEIVED, 0.0),
        TraceEvent("req::repeat0::0", LifecycleStage.TOKENIZED, 0.5),
        TraceEvent("req::repeat0::0", LifecycleStage.QUEUED, 0.6),
        TraceEvent("req::repeat0::0", LifecycleStage.SCHEDULED, 1.0),
        TraceEvent("req::repeat0::0", LifecycleStage.PREFILL_DONE, 9.0),
        TraceEvent("req::repeat0::0", LifecycleStage.FIRST_TOKEN, 9.0),
        TraceEvent("req::repeat0::0", LifecycleStage.DECODE_DONE, 29.0),
        TraceEvent("req::repeat0::0", LifecycleStage.STREAM_DONE, 29.0),
        TraceEvent("req::repeat0::0", LifecycleStage.CLEANUP_DONE, 30.0),
    )

    result = module.analyze_events(list(events))

    assert result["summary"]["request_count"] == 2
    assert result["summary"]["measured_request_count"] == 1
    assert result["summary"]["dominant_bottleneck"] == "decode"
    assert result["summary"]["dominant_bottleneck_counts"] == {"decode": 1}
    assert result["summary"]["measured_span_duration_ms"]["decode"]["p50"] == 20.0
    assert result["summary"]["missing_event_rate"]["max"] == 0.0
