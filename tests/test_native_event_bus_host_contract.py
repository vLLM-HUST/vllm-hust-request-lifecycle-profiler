from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from vllm_request_lifecycle_profiler.native_event_bus import NativeLifecycleEventSink


def load_current_host_events() -> ModuleType:
    source = os.getenv("VLLM_HUST_SOURCE")
    if not source:
        pytest.skip("VLLM_HUST_SOURCE is not configured")
    path = Path(source) / "vllm" / "v1" / "events.py"
    if not path.is_file():
        pytest.fail(f"current host event contract is missing: {path}")
    name = "_ecpa_current_vllm_events"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_current_host_event_bus_drives_native_sink() -> None:
    events = load_current_host_events()
    assert events.REQUEST_LIFECYCLE_EVENTS_API_VERSION == "1.0"
    events.EventBus._sinks = []
    events.EventBus.enabled = False
    drafts: list[object] = []
    evidence: list[tuple[str, str]] = []
    hooks = SimpleNamespace(
        enabled=True,
        emit_event=lambda draft: drafts.append(draft),
    )
    sink = NativeLifecycleEventSink(
        hooks,
        "host-contract",
        finished_type=events.RequestFinished,
        preempted_type=events.RequestPreempted,
        reclaimed_type=events.RequestKvReclaimed,
        evidence_emitter=lambda name, request_id: evidence.append(
            (name, request_id)
        )
        is None,
    )
    events.EventBus.register_sink(sink)
    events.EventBus.emit(
        events.RequestFinished(
            request_id="request-1",
            session_id=None,
            prompt_tokens=3,
            output_tokens=2,
            sequence_tokens=5,
            kv_blocks=1,
            kv_reclaim_deferred=False,
            finished_reason="stop",
        )
    )
    events.EventBus.unregister_sink(sink)

    assert [draft.event_name for draft in drafts] == ["request_finished_observed"]
    assert evidence == [("request_finished", "request-1")]
    assert events.EventBus.enabled is False
