from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

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

SCHEDULER_DIAGNOSTICS_PATH_ENV = "VLLM_RLP_SCHEDULER_DIAGNOSTICS_PATH"

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


def initialize_lifecycle_profile_runtime() -> RuntimeLifecycleHooks | None:
    """Initialize the lifecycle exporter in the calling runtime process."""

    if _REGISTERED_PID != os.getpid():
        register_plugin()
    return _RUNTIME_HOOKS


def get_lifecycle_profile_runtime() -> RuntimeLifecycleHooks | None:
    """Return this process's lifecycle exporter, if initialized."""

    if _REGISTERED_PID != os.getpid():
        return None
    return _RUNTIME_HOOKS


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
        result = runtime.close()
    except Exception:
        logger.exception("Failed to close the optional scheduler profiler.")
        return None
    if isinstance(result, SchedulerCloseResult) and not result.writer_complete:
        logger.warning(
            "Scheduler profiler closed without a formal shard: outcome=%s, "
            "writer_failures=%d, invalid_reasons=%s",
            result.close_outcome,
            result.writer_failure_count,
            result.formal_invalid_reasons,
        )
    if isinstance(result, SchedulerCloseResult) and result.writer_complete:
        try:
            _write_scheduler_runtime_diagnostics(result)
        except Exception:
            logger.exception("Failed to publish scheduler runtime diagnostics.")
    return result


def close_lifecycle_profile_runtime() -> object | None:
    """Close the lifecycle stream without allowing shutdown failures."""

    runtime = get_lifecycle_profile_runtime()
    if runtime is None:
        return None
    try:
        return runtime.close()
    except Exception:
        logger.exception("Failed to close the optional lifecycle profiler.")
        return None


def _write_scheduler_runtime_diagnostics(result: SchedulerCloseResult) -> None:
    """Publish the optional I6 diagnostic sidecar without changing wire bytes."""

    configured = os.environ.get(SCHEDULER_DIAGNOSTICS_PATH_ENV, "").strip()
    if not configured:
        return
    target = Path(configured)
    if not target.is_absolute() or result.shard_path is None:
        raise ValueError("scheduler diagnostics path must be absolute")
    shard_sha256 = hashlib.sha256(result.shard_path.read_bytes()).hexdigest()
    payload = {
        "schema_version": 1,
        "artifact_kind": "scheduler_profile_runtime_diagnostics",
        "scheduler_shard_sha256": shard_sha256,
        "max_writer_service_gap_ms": result.max_writer_service_gap_ns / 1_000_000,
        "max_queued_bytes_observed": result.max_queued_bytes_observed,
        "max_queued_records_observed": result.max_queued_records_observed,
        "diagnostic_clock_failure_count": result.diagnostic_clock_failure_count,
    }
    raw = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() == raw:
            return
        raise FileExistsError(f"scheduler diagnostics path already exists: {target}")
    incomplete = target.with_name(f".{target.name}.incomplete.{os.getpid()}")
    fd = -1
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
        fd = os.open(incomplete, flags, 0o600)
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("scheduler diagnostics writer made no progress")
            view = view[written:]
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.link(incomplete, target)
    finally:
        if fd >= 0:
            os.close(fd)
        incomplete.unlink(missing_ok=True)
