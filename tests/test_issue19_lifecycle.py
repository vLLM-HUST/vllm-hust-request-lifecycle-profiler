from __future__ import annotations

from unittest.mock import Mock

from vllm_request_lifecycle_profiler.issue19_lifecycle import (
    Issue19LifecycleObserver,
)


def test_observer_tracks_duplicate_abort_and_bounded_resource_seam() -> None:
    hooks = Mock()
    bridge = Mock()
    bridge.register_runtime_request.return_value = True
    observer = Issue19LifecycleObserver(
        hooks,
        bridge,
        "a" * 32,
        capacity=2,
        clock_ns=iter((1, 2, 3, 4, 5)).__next__,
    )

    observer.request_started("request-0")
    observer.abort_attempt("request-0")
    observer.abort_attempt("request-0")
    observer.resource_transition("request-0", "kv", "block-0", "acquire", "g0")
    observer.resource_transition("request-0", "kv", "block-0", "release", "g0")
    observer.resource_transition("request-0", "kv", "block-1", "acquire", "g0")
    observer.request_terminal("request-0", "explicit_cancel")

    assert observer.abort_attempts == {"request-0": 2}
    assert [row.transition for row in observer.resource_observations] == [
        "acquire",
        "release",
    ]
    assert [call.args[0].event_name for call in hooks.emit_event.call_args_list] == [
        "resource_acquired",
        "resource_released",
    ]
    bridge.emit_runtime_terminal.assert_called_once_with(
        "request-0",
        "explicit_cancel",
        timestamp_ns=5,
        generated_tokens_total=0,
    )


def test_observer_callbacks_are_fail_open() -> None:
    hooks = Mock()
    bridge = Mock()
    bridge.register_runtime_request.side_effect = RuntimeError("observer failure")
    bridge.emit_runtime_terminal.side_effect = RuntimeError("observer failure")
    observer = Issue19LifecycleObserver(
        hooks,
        bridge,
        "a" * 32,
        clock_ns=lambda: 1,
    )

    observer.request_started("request-0")
    observer.request_terminal("request-0", "engine_failure")
    observer.engine_failure(("request-0",))
    observer.worker_generation_exit("worker-0", worker_pid=10, exit_code=1)

    assert observer.abort_attempts == {}


def test_resource_observation_is_not_counted_when_export_rejects_it() -> None:
    hooks = Mock()
    hooks.emit_event.return_value = None
    observer = Issue19LifecycleObserver(
        hooks,
        Mock(),
        "a" * 32,
        clock_ns=lambda: 1,
    )

    observer.resource_transition("request-0", "kv", "lease-0", "acquire", "g0")

    assert observer.resource_observations == ()


def test_non_ascii_resource_identity_reaches_protocol_validation() -> None:
    hooks = Mock()
    hooks.emit_event.return_value = None
    observer = Issue19LifecycleObserver(
        hooks,
        Mock(),
        "a" * 32,
        clock_ns=lambda: 1,
    )

    observer.resource_transition(
        "请求-0", "kv_capacity_lease", "lease-0", "acquire", "EngineCore:10"
    )

    assert observer.resource_observations == ()
    assert hooks.emit_event.call_args.args[0].metadata["runtime_request_id"] == "请求-0"
