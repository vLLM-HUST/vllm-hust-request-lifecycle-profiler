from __future__ import annotations

import os
import sys
from types import ModuleType, SimpleNamespace

from vllm_request_lifecycle_profiler import plugin
from vllm_request_lifecycle_profiler.kv_recovery_profile_protocol import (
    KVRecoveryProfileConfig,
)
from vllm_request_lifecycle_profiler.runtime_protocol import (
    KV_RECOVERY_COMMUNICATION_MODE,
)

RUN_ID = "4" * 32


def install_fake_vllm(monkeypatch, register):
    vllm = ModuleType("vllm")
    envs = ModuleType("vllm.envs")
    v1 = ModuleType("vllm.v1")
    recovery = ModuleType("vllm.v1.kv_recovery_profile")
    recovery.register_kv_recovery_observer_factory = register
    vllm.envs = envs
    vllm.v1 = v1
    v1.kv_recovery_profile = recovery
    monkeypatch.setitem(sys.modules, "vllm", vllm)
    monkeypatch.setitem(sys.modules, "vllm.envs", envs)
    monkeypatch.setitem(sys.modules, "vllm.v1", v1)
    monkeypatch.setitem(sys.modules, "vllm.v1.kv_recovery_profile", recovery)
    return envs


def reset_plugin(monkeypatch):
    monkeypatch.setattr(plugin, "_REGISTERED_PID", None)
    monkeypatch.setattr(plugin, "_RUNTIME_HOOKS", None)
    monkeypatch.setattr(plugin, "_RUNTIME_BRIDGE", None)
    monkeypatch.setattr(plugin, "_OBSERVER_FACTORY", None)
    monkeypatch.setattr(plugin, "_SCHEDULER_RUNTIME", None)


def test_register_plugin_keeps_default_configuration_inactive(monkeypatch) -> None:
    reset_plugin(monkeypatch)
    envs = install_fake_vllm(
        monkeypatch,
        lambda factory: (_ for _ in ()).throw(
            AssertionError("disabled configuration registered a factory")
        ),
    )
    hooks = SimpleNamespace(
        enabled=False,
        config=SimpleNamespace(
            communication_mode="none", kv_recovery_profile_config=None
        ),
    )
    monkeypatch.setattr(plugin.RuntimeLifecycleHooks, "from_env", lambda: hooks)

    plugin.register_plugin()

    assert envs.VLLM_GENERAL_PLUGIN_TEMPLATE_LOADED is True
    assert plugin._RUNTIME_HOOKS is hooks
    assert plugin._OBSERVER_FACTORY is None


def test_register_plugin_uses_explicit_recovery_configuration(monkeypatch) -> None:
    reset_plugin(monkeypatch)
    registered = []
    install_fake_vllm(monkeypatch, registered.append)
    config = KVRecoveryProfileConfig(run_id=RUN_ID)
    hooks = SimpleNamespace(
        enabled=True,
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


def test_scheduler_runtime_is_process_local_singleton_and_closes(
    monkeypatch,
) -> None:
    reset_plugin(monkeypatch)
    profile = object()
    hooks = object()
    closed = object()
    runtime = SimpleNamespace(close=lambda: closed)
    created = []
    monkeypatch.setattr(plugin, "_REGISTERED_PID", os.getpid())
    monkeypatch.setattr(plugin, "_RUNTIME_HOOKS", hooks)
    monkeypatch.setattr(
        plugin,
        "create_scheduler_profile_runtime",
        lambda observed_profile, observed_hooks: (
            created.append((observed_profile, observed_hooks)) or runtime
        ),
    )

    first = plugin.initialize_scheduler_profile_runtime(profile)  # type: ignore[arg-type]
    second = plugin.initialize_scheduler_profile_runtime(profile)  # type: ignore[arg-type]

    assert first is runtime
    assert second is runtime
    assert created == [(profile, hooks)]
    assert plugin.get_scheduler_profile_runtime() is runtime
    assert plugin.close_scheduler_profile_runtime() is closed
