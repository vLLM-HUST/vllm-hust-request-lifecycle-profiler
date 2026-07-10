from __future__ import annotations

import json
from pathlib import Path

from vllm_request_lifecycle_profiler.runtime_hooks import RuntimeLifecycleHooks
from vllm_request_lifecycle_profiler.runtime_hooks import RuntimeTraceConfig
from vllm_request_lifecycle_profiler.runtime_hooks import TRACE_EXPORT_ENV
from vllm_request_lifecycle_profiler.trace import LifecycleStage
from vllm_request_lifecycle_profiler.trace import compute_spans


def test_runtime_trace_config_is_disabled_without_export_path() -> None:
    config = RuntimeTraceConfig.from_env({})

    assert config.enabled is False
    assert config.export_path is None


def test_runtime_hooks_write_schema_compatible_jsonl(tmp_path) -> None:
    trace_path = tmp_path / "runtime_trace.jsonl"
    hooks = RuntimeLifecycleHooks.from_env({TRACE_EXPORT_ENV: str(trace_path)})

    hooks.received("req-1", timestamp_ms=1.0, model="qwen")
    hooks.tokenized("req-1", timestamp_ms=3.0, prompt_tokens=128)
    hooks.queued("req-1", timestamp_ms=4.0)
    hooks.scheduled("req-1", timestamp_ms=9.0, queue_depth=2)
    hooks.first_token("req-1", timestamp_ms=19.0, kv_cache_pressure_ratio=0.5)

    rows = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [row["stage"] for row in rows] == [
        "received",
        "tokenized",
        "queued",
        "scheduled",
        "first_token",
    ]
    assert rows[0]["metadata"] == {
        "model": "qwen",
        "observer": "vllm_runtime_hook",
    }
    assert rows[-1]["metadata"]["kv_cache_pressure_ratio"] == 0.5

    events = [
        hooks.emit("req-2", LifecycleStage.RECEIVED, timestamp_ms=0.0),
        hooks.emit("req-2", LifecycleStage.TOKENIZED, timestamp_ms=2.0),
        hooks.emit("req-2", LifecycleStage.QUEUED, timestamp_ms=3.0),
        hooks.emit("req-2", LifecycleStage.SCHEDULED, timestamp_ms=8.0),
        hooks.emit("req-2", LifecycleStage.PREFILL_DONE, timestamp_ms=18.0),
        hooks.emit("req-2", LifecycleStage.FIRST_TOKEN, timestamp_ms=18.0),
        hooks.emit("req-2", LifecycleStage.DECODE_DONE, timestamp_ms=28.0),
        hooks.emit("req-2", LifecycleStage.STREAM_DONE, timestamp_ms=31.0),
        hooks.emit("req-2", LifecycleStage.CLEANUP_DONE, timestamp_ms=32.0),
    ]
    spans = compute_spans(events)
    assert [(span.name, span.duration_ms) for span in spans] == [
        ("tokenization", 2.0),
        ("queueing", 5.0),
        ("prefill", 10.0),
        ("decode", 10.0),
        ("streaming", 3.0),
        ("cleanup", 1.0),
    ]


def test_runtime_hooks_noop_when_disabled(tmp_path) -> None:
    hooks = RuntimeLifecycleHooks.from_env({})
    event = hooks.scheduled("req-disabled", timestamp_ms=7.0)

    assert event.stage is LifecycleStage.SCHEDULED
    assert event.metadata == {"observer": "vllm_runtime_hook"}
    assert list(tmp_path.iterdir()) == []


def test_pinned_vllm_hust_hook_sites_cover_stream_done() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    output_processor = (
        repo_root
        / "third_party"
        / "vllm-hust"
        / "vllm"
        / "v1"
        / "engine"
        / "output_processor.py"
    )
    source = output_processor.read_text(encoding="utf-8")

    assert "lifecycle_stream_done_emitted" in source
    assert "def _emit_lifecycle_stream_done" in source
    assert '"stream_done"' in source
