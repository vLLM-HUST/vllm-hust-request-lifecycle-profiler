from __future__ import annotations

import logging
import os

from vllm_request_lifecycle_profiler.runtime_hooks import RuntimeLifecycleHooks
from vllm_request_lifecycle_profiler.runtime_protocol import (
    KV_RECOVERY_COMMUNICATION_MODE,
)
from vllm_request_lifecycle_profiler.scheduler_profile import SchedulerCloseResult
from vllm_request_lifecycle_profiler.scheduler_profile_runtime import (
    NullSchedulerProfileRuntime,
    SchedulerProfileRuntime,
    SchedulerRuntimeProfile,
    create_scheduler_profile_runtime,
)

logger = logging.getLogger(__name__)

_REGISTERED_PID: int | None = None
_RUNTIME_HOOKS: RuntimeLifecycleHooks | None = None
_RUNTIME_BRIDGE: object | None = None
_OBSERVER_FACTORY: object | None = None
_SCHEDULER_RUNTIME: SchedulerProfileRuntime | NullSchedulerProfileRuntime | None = None


def register_plugin() -> None:
    """Register the plugin.

    This function must be re-entrant because vLLM can load general plugins in
    multiple processes.
    """

    global _OBSERVER_FACTORY, _REGISTERED_PID, _RUNTIME_BRIDGE, _RUNTIME_HOOKS
    global _SCHEDULER_RUNTIME
    process_id = os.getpid()
    if _REGISTERED_PID == process_id:
        return

    _SCHEDULER_RUNTIME = None

    try:
        from vllm import envs as vllm_envs
    except Exception:
        logger.exception("Failed to import vLLM during plugin registration.")
        return

    vllm_envs.VLLM_GENERAL_PLUGIN_TEMPLATE_LOADED = True

    hooks = RuntimeLifecycleHooks.from_env()
    if (
        hooks.enabled
        and hooks.config.communication_mode == KV_RECOVERY_COMMUNICATION_MODE
        and hooks.config.kv_recovery_profile_config is not None
    ):
        try:
            from vllm.v1.kv_recovery_profile import (
                register_kv_recovery_observer_factory,
            )

            from vllm_request_lifecycle_profiler.kv_recovery_runtime import (
                KVRecoveryObserverFactoryAdapter,
                KVRecoveryRuntimeABI,
                RuntimeBaseLifecycleBridge,
            )

            profile_config = hooks.config.kv_recovery_profile_config
            bridge = RuntimeBaseLifecycleBridge(hooks)
            factory = KVRecoveryObserverFactoryAdapter(
                profile_config.run_id,
                hooks,
                bridge,
                KVRecoveryRuntimeABI.load(),
            )
            register_kv_recovery_observer_factory(factory)
            _RUNTIME_BRIDGE = bridge
            _OBSERVER_FACTORY = factory
            logger.info("Registered the optional KV-recovery profiler.")
        except Exception:
            logger.exception("Failed to register the optional KV-recovery profiler.")

    _RUNTIME_HOOKS = hooks
    _REGISTERED_PID = process_id


def initialize_scheduler_profile_runtime(
    profile: SchedulerRuntimeProfile,
) -> SchedulerProfileRuntime | NullSchedulerProfileRuntime:
    """Initialize the scheduler stream after EngineCore resolves its profile."""

    global _SCHEDULER_RUNTIME
    if _REGISTERED_PID != os.getpid():
        register_plugin()
    if _SCHEDULER_RUNTIME is None:
        _SCHEDULER_RUNTIME = create_scheduler_profile_runtime(profile, _RUNTIME_HOOKS)
    return _SCHEDULER_RUNTIME


def get_scheduler_profile_runtime(
) -> SchedulerProfileRuntime | NullSchedulerProfileRuntime | None:
    """Return this process's initialized scheduler stream, if any."""

    if _REGISTERED_PID != os.getpid():
        return None
    return _SCHEDULER_RUNTIME


def close_scheduler_profile_runtime() -> SchedulerCloseResult | None:
    """Close the scheduler stream without allowing shutdown failures."""

    runtime = get_scheduler_profile_runtime()
    if runtime is None:
        return None
    try:
        return runtime.close()
    except Exception:
        logger.exception("Failed to close the optional scheduler profiler.")
        return None
