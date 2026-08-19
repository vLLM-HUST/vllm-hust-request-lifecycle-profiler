from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

from vllm_request_lifecycle_profiler import plugin
from vllm_request_lifecycle_profiler.kv_recovery_profile_protocol import (
    KVRecoveryProfileConfig,
)
from vllm_request_lifecycle_profiler.runtime_protocol import (
    KV_RECOVERY_COMMUNICATION_MODE,
)
from vllm_request_lifecycle_profiler.scheduler_profile import SchedulerCloseResult

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


def test_lifecycle_runtime_is_process_local_and_closes(monkeypatch) -> None:
    reset_plugin(monkeypatch)
    closed = object()
    hooks = SimpleNamespace(close=lambda: closed)
    monkeypatch.setattr(plugin, "_REGISTERED_PID", os.getpid())
    monkeypatch.setattr(plugin, "_RUNTIME_HOOKS", hooks)

    assert plugin.initialize_lifecycle_profile_runtime() is hooks
    assert plugin.get_lifecycle_profile_runtime() is hooks
    assert plugin.close_lifecycle_profile_runtime() is closed

    monkeypatch.setattr(plugin, "_REGISTERED_PID", os.getpid() + 1)
    assert plugin.get_lifecycle_profile_runtime() is None


def test_scheduler_close_publishes_optional_i6_diagnostics(
    monkeypatch, tmp_path: Path
) -> None:
    reset_plugin(monkeypatch)
    shard = tmp_path / "scheduler.jsonl"
    shard.write_text("{}\n", encoding="utf-8")
    result = SchedulerCloseResult(
        close_outcome="drained",
        summary_written=True,
        attempted_data_count=1,
        written_loss_interval_count=0,
        dropped_data_count=0,
        dropped_control_count=0,
        writer_failure_count=0,
        artifact_bytes_written=3,
        max_writer_service_gap_ns=2_500_000,
        max_queued_bytes_observed=512,
        max_queued_records_observed=2,
        diagnostic_clock_failure_count=0,
        formal_invalid_reasons=(),
        shard_path=shard,
    )
    diagnostics = tmp_path / "diagnostics" / "runtime.json"
    monkeypatch.setenv(plugin.SCHEDULER_DIAGNOSTICS_PATH_ENV, str(diagnostics))
    monkeypatch.setattr(plugin, "_REGISTERED_PID", os.getpid())
    monkeypatch.setattr(plugin, "_SCHEDULER_RUNTIME", SimpleNamespace(close=lambda: result))

    assert plugin.close_scheduler_profile_runtime() is result
    payload = json.loads(diagnostics.read_text(encoding="utf-8"))
    assert payload["max_writer_service_gap_ms"] == 2.5
    assert payload["max_queued_bytes_observed"] == 512
    assert payload["max_queued_records_observed"] == 2
    assert payload["diagnostic_clock_failure_count"] == 0
    assert diagnostics.stat().st_mode & 0o777 == 0o600
