from __future__ import annotations

from vllm_request_lifecycle_profiler.launcher import _merge_plugins


def test_merge_plugins_when_empty() -> None:
    assert _merge_plugins(None, "request_lifecycle_profiler") == "request_lifecycle_profiler"


def test_merge_plugins_appends_once() -> None:
    merged = _merge_plugins("foo,bar", "request_lifecycle_profiler")
    assert merged == "foo,bar,request_lifecycle_profiler"
    assert _merge_plugins(merged, "request_lifecycle_profiler") == merged