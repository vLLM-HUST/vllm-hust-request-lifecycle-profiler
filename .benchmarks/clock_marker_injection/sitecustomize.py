"""Experiment-only vLLM-Ascend worker marker injection.

This module is loaded through ``PYTHONPATH`` in both matched A/B variants. It
wraps the installed vLLM-Ascend worker without modifying the shared Python
installation. Iteration timing is collected in both variants; only the marker
enabled variant sets the bracket export environment variable.
"""

from __future__ import annotations

import atexit
import fcntl
import functools
import importlib.abc
import importlib.machinery
import importlib.util
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any

TARGET_MODULE = "vllm_ascend.worker.worker"
ITERATION_TIMINGS_ENV = "VLLM_RLP_ASCEND_ITERATION_TIMINGS_PATH"
PROFILER_DEVICE_ID_ENV = "VLLM_RLP_ASCEND_PROFILER_DEVICE_ID"
ITERATION_HEADER = (
    "iteration_id\thost_start_ns\thost_end_ns\tduration_ns\thost_pid\t"
    "host_tid\tscheduled_token_count\tmarker_state\n"
)
logger = logging.getLogger(__name__)
_collector: Any | None = None
_collector_initialized = False
_iteration_sequence = 0
_state_lock = threading.Lock()


def _write_all(fd: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(fd, payload[offset:])
        if written <= 0:
            raise OSError("short write while exporting iteration timing")
        offset += written


def _append_iteration(
    *,
    iteration_id: int,
    host_start_ns: int,
    host_end_ns: int,
    scheduled_token_count: int,
    marker_state: str,
) -> None:
    raw_path = os.environ.get(ITERATION_TIMINGS_ENV, "").strip()
    if not raw_path:
        return
    path = os.path.abspath(raw_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        if os.fstat(fd).st_size == 0:
            _write_all(fd, ITERATION_HEADER.encode())
        line = (
            f"{iteration_id}\t{host_start_ns}\t{host_end_ns}\t"
            f"{host_end_ns - host_start_ns}\t{os.getpid()}\t"
            f"{threading.get_native_id()}\t{scheduled_token_count}\t"
            f"{marker_state}\n"
        )
        _write_all(fd, line.encode())
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _get_collector() -> Any | None:
    global _collector, _collector_initialized
    with _state_lock:
        if _collector_initialized:
            return _collector
        _collector_initialized = True
        try:
            from vllm_request_lifecycle_profiler import AscendClockMarkerCollector

            _collector = AscendClockMarkerCollector.from_env(
                device_id=int(os.environ.get(PROFILER_DEVICE_ID_ENV, "6")),
                call_site="vllm_ascend.NPUWorker.execute_model",
            )
            if _collector is not None:
                atexit.register(_collector.close)
        except Exception:
            logger.exception("failed to initialize Ascend clock marker collector")
            _collector = None
        return _collector


def _patch_worker(module: ModuleType) -> None:
    worker_class = getattr(module, "NPUWorker", None)
    if worker_class is None or getattr(
        worker_class, "_vllm_rlp_clock_marker_patched", False
    ):
        return
    original = worker_class.execute_model

    @functools.wraps(original)
    def execute_model_with_clock_marker(
        self: Any, scheduler_output: Any, *args: Any, **kwargs: Any
    ) -> Any:
        global _iteration_sequence
        with _state_lock:
            iteration_id = _iteration_sequence
            _iteration_sequence += 1
        host_start_ns = time.perf_counter_ns()
        marker_state = "disabled"
        collector = _get_collector()
        if collector is not None:
            try:
                bracket = collector.record()
                marker_state = (
                    "recorded" if bracket.return_status == 0 else "runtime_error"
                )
            except Exception:
                logger.exception("Ascend clock marker collection failed")
                marker_state = "collector_error"
        try:
            return original(self, scheduler_output, *args, **kwargs)
        finally:
            host_end_ns = time.perf_counter_ns()
            scheduled_token_count = int(
                getattr(scheduler_output, "total_num_scheduled_tokens", 0)
            )
            _append_iteration(
                iteration_id=iteration_id,
                host_start_ns=host_start_ns,
                host_end_ns=host_end_ns,
                scheduled_token_count=scheduled_token_count,
                marker_state=marker_state,
            )

    worker_class.execute_model = execute_model_with_clock_marker
    worker_class._vllm_rlp_clock_marker_patched = True


class _WorkerLoader(importlib.abc.Loader):
    def __init__(self, delegate: importlib.abc.Loader) -> None:
        self._delegate = delegate

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> ModuleType | None:
        creator = getattr(self._delegate, "create_module", None)
        return None if creator is None else creator(spec)

    def exec_module(self, module: ModuleType) -> None:
        self._delegate.exec_module(module)
        _patch_worker(module)


class _WorkerFinder(importlib.abc.MetaPathFinder):
    def find_spec(
        self,
        fullname: str,
        path: list[str] | None,
        target: ModuleType | None = None,
    ) -> importlib.machinery.ModuleSpec | None:
        del target
        if fullname != TARGET_MODULE:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or spec.loader is None:
            return spec
        if not isinstance(spec.loader, importlib.abc.Loader):
            return spec
        spec.loader = _WorkerLoader(spec.loader)
        return spec


sys.meta_path.insert(0, _WorkerFinder())
