from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import ClassVar

import pytest

from vllm_request_lifecycle_profiler import plugin
from vllm_request_lifecycle_profiler.kv_recovery_profile_protocol import (
    KVRecoveryProfileConfig,
)
from vllm_request_lifecycle_profiler.runtime_protocol import (
    KV_RECOVERY_COMMUNICATION_MODE,
)

RUN_ID = "4" * 32


def install_fake_vllm(monkeypatch, register, *, api_version="1.0"):
    vllm = ModuleType("vllm")
    envs = ModuleType("vllm.envs")
    v1 = ModuleType("vllm.v1")
    recovery = ModuleType("vllm.v1.kv_recovery_profile")
    events = ModuleType("vllm.v1.events")

    class EventBus:
        sinks: ClassVar[list] = []

        @classmethod
        def register_sink(cls, sink):
            cls.sinks.append(sink)

        @classmethod
        def unregister_sink(cls, sink):
            if sink in cls.sinks:
                cls.sinks.remove(sink)

    class RequestFinished:
        pass

    class RequestPreempted:
        pass

    class RequestKvReclaimed:
        pass

    events.EventBus = EventBus
    events.REQUEST_LIFECYCLE_EVENTS_API_VERSION = api_version
    events.RequestFinished = RequestFinished
    events.RequestPreempted = RequestPreempted
    events.RequestKvReclaimed = RequestKvReclaimed
    recovery.register_kv_recovery_observer_factory = register
    vllm.envs = envs
    vllm.v1 = v1
    v1.kv_recovery_profile = recovery
    v1.events = events
    monkeypatch.setitem(sys.modules, "vllm", vllm)
    monkeypatch.setitem(sys.modules, "vllm.envs", envs)
    monkeypatch.setitem(sys.modules, "vllm.v1", v1)
    monkeypatch.setitem(sys.modules, "vllm.v1.kv_recovery_profile", recovery)
    monkeypatch.setitem(sys.modules, "vllm.v1.events", events)
    return events


def reset_plugin(monkeypatch):
    monkeypatch.setattr(plugin, "_REGISTERED_PID", None)
    monkeypatch.setattr(plugin, "_RUNTIME_HOOKS", None)
    monkeypatch.setattr(plugin, "_RUNTIME_BRIDGE", None)
    monkeypatch.setattr(plugin, "_OBSERVER_FACTORY", None)
    monkeypatch.setattr(plugin, "_NATIVE_EVENT_BUS", None)
    monkeypatch.setattr(plugin, "_NATIVE_EVENT_SINK", None)


def test_register_plugin_keeps_default_configuration_inactive(monkeypatch) -> None:
    reset_plugin(monkeypatch)
    events = install_fake_vllm(
        monkeypatch,
        lambda factory: (_ for _ in ()).throw(
            AssertionError("disabled configuration registered a factory")
        ),
    )
    hooks = SimpleNamespace(
        enabled=False,
        process_uuid=None,
        config=SimpleNamespace(
            communication_mode="none", kv_recovery_profile_config=None
        ),
    )
    monkeypatch.setattr(plugin.RuntimeLifecycleHooks, "from_env", lambda: hooks)

    plugin.register_plugin()

    assert len(events.EventBus.sinks) == 1
    assert plugin._RUNTIME_HOOKS is hooks
    assert plugin._OBSERVER_FACTORY is None
    assert plugin.get_native_event_sink() is not None


def test_register_plugin_rejects_incompatible_event_api(monkeypatch) -> None:
    reset_plugin(monkeypatch)
    install_fake_vllm(monkeypatch, lambda _factory: None, api_version="2.0")

    with pytest.raises(RuntimeError, match="unsupported.*2.0"):
        plugin.register_plugin()


def test_register_plugin_uses_explicit_recovery_configuration(monkeypatch) -> None:
    reset_plugin(monkeypatch)
    registered = []
    install_fake_vllm(monkeypatch, registered.append)
    config = KVRecoveryProfileConfig(run_id=RUN_ID)
    hooks = SimpleNamespace(
        enabled=True,
        process_uuid="5" * 32,
        config=SimpleNamespace(
            communication_mode=KV_RECOVERY_COMMUNICATION_MODE,
            kv_recovery_profile_config=config,
        ),
    )
    monkeypatch.setattr(plugin.RuntimeLifecycleHooks, "from_env", lambda: hooks)

    from vllm_request_lifecycle_profiler import kv_recovery_runtime

    monkeypatch.setattr(
        kv_recovery_runtime.KVRecoveryRuntimeABI,
        "load",
        classmethod(lambda cls: SimpleNamespace()),
    )

    plugin.register_plugin()

    assert registered == [plugin._OBSERVER_FACTORY]
    assert plugin._RUNTIME_BRIDGE is not None
    assert plugin._RUNTIME_HOOKS is hooks
    assert plugin.get_native_event_sink() is not None


def test_close_native_event_sink_unregisters_without_stopping_host(monkeypatch) -> None:
    reset_plugin(monkeypatch)
    install_fake_vllm(monkeypatch, lambda _factory: None)
    hooks = SimpleNamespace(
        enabled=False,
        process_uuid=None,
        config=SimpleNamespace(
            communication_mode="none", kv_recovery_profile_config=None
        ),
    )
    monkeypatch.setattr(plugin.RuntimeLifecycleHooks, "from_env", lambda: hooks)

    plugin.register_plugin()
    event_bus = plugin._NATIVE_EVENT_BUS
    assert len(event_bus.sinks) == 1

    plugin.close_native_event_sink()

    assert event_bus.sinks == []
    assert plugin.get_native_event_sink() is None
