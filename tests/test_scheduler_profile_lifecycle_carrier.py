from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from vllm_request_lifecycle_profiler.runtime_protocol import build_event_record

ROOT = Path(__file__).resolve().parents[1]
CARRIER_PATH = (
    ROOT
    / "runtime"
    / "vllm_021"
    / "vllm"
    / "v1"
    / "engine"
    / "scheduler_profile_hooks.py"
)
PROCESS_ID = "1" * 32
CLOCK_ID = "2" * 32


@pytest.fixture
def carrier() -> ModuleType:
    name = "_test_scheduler_profile_lifecycle_carrier"
    spec = importlib.util.spec_from_file_location(name, CARRIER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(name, None)


class _Hooks:
    enabled = True

    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []
        self._span_seq = 0

    def new_span_id(self) -> str:
        value = f"{PROCESS_ID}:s:{self._span_seq}"
        self._span_seq += 1
        return value

    def emit_event(self, draft):
        record, reference = build_event_record(
            draft,
            process_uuid=PROCESS_ID,
            clock_domain_id=CLOCK_ID,
            record_seq=len(self.events),
            default_timestamp_ns=len(self.events) + 1,
        )
        self.events.append(record)
        return reference


def test_engine_carrier_emits_positive_bounded_lifecycle(
    carrier: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    hooks = _Hooks()
    monkeypatch.setenv(carrier.LIFECYCLE_EXPORT_ENV, "/tmp/trace")
    monkeypatch.setenv(carrier.SCHEDULER_EXPORT_ENV, "/tmp/scheduler")
    monkeypatch.setattr(carrier, "get_lifecycle_profile_runtime", lambda: hooks)
    headers = carrier.prepare_request_profile_headers("request-1", None, 1)
    request = SimpleNamespace(
        request_id="request-1",
        trace_headers=headers,
        num_prompt_tokens=8,
        num_preemptions=0,
        num_output_tokens=4,
    )

    carrier.lifecycle_request_admitted(request)
    carrier.lifecycle_request_scheduled(request, 0)
    carrier.lifecycle_request_finished(request)

    assert headers[carrier.SAMPLING_N_HEADER] == "1"
    assert len(headers[carrier.TRACE_ID_HEADER]) == 32
    assert [event["event_name"] for event in hooks.events] == [
        "queued",
        "scheduled",
        "generation_done",
        "cleanup_started",
        "cleanup_done",
    ]
    assert {event["trace_id"] for event in hooks.events} == {
        headers[carrier.TRACE_ID_HEADER]
    }
    assert hooks.events[1]["end_span_id"] == hooks.events[0]["start_span_id"]
    assert hooks.events[4]["end_span_id"] == hooks.events[3]["start_span_id"]
    assert not carrier._LIFECYCLE_STATES


def test_lifecycle_only_initializes_engine_exporter(
    carrier: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vllm_request_lifecycle_profiler import plugin

    calls: list[str] = []
    monkeypatch.setenv(carrier.LIFECYCLE_EXPORT_ENV, "/tmp/trace")
    monkeypatch.delenv(carrier.SCHEDULER_EXPORT_ENV, raising=False)
    monkeypatch.setattr(
        plugin,
        "initialize_lifecycle_profile_runtime",
        lambda: calls.append("lifecycle"),
    )

    assert carrier.initialize_scheduler_profile_runtime(object(), 1) is None
    assert calls == ["lifecycle"]


def test_profile_headers_are_default_off(carrier: ModuleType) -> None:
    headers = carrier.prepare_request_profile_headers(
        "request-1", {"traceparent": "value"}, 1
    )

    assert headers == {"traceparent": "value"}
