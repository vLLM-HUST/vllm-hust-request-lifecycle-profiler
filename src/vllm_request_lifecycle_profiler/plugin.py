from __future__ import annotations

import logging
import os

from vllm_request_lifecycle_profiler.runtime_hooks import RuntimeLifecycleHooks
from vllm_request_lifecycle_profiler.runtime_protocol import (
    KV_RECOVERY_COMMUNICATION_MODE,
)

logger = logging.getLogger(__name__)

_REGISTERED_PID: int | None = None
_RUNTIME_HOOKS: RuntimeLifecycleHooks | None = None
_RUNTIME_BRIDGE: object | None = None
_OBSERVER_FACTORY: object | None = None


def register_plugin() -> None:
    """Register the plugin.

    This function must be re-entrant because vLLM can load general plugins in
    multiple processes.
    """

    global _OBSERVER_FACTORY, _REGISTERED_PID, _RUNTIME_BRIDGE, _RUNTIME_HOOKS
    process_id = os.getpid()
    if _REGISTERED_PID == process_id:
        return

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
