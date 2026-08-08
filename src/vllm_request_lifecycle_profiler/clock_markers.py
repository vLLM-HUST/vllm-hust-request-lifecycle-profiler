"""Ascend host-bracket collection for host-to-device clock calibration.

The collector deliberately does not export ``aclrtEventGetTimestamp`` as a
device nanosecond timestamp: that API returns a raw device syscnt. Instead it
records one narrow CLOCK_REALTIME bracket around ``aclrtRecordEvent`` and one
outer bracket through event synchronization. TraceLoom later resolves the
profiled record call through its
unique connectionId to ``TASK.startNs``, which is in the profiler's device
clock domain.
"""

from __future__ import annotations

import ctypes
import fcntl
import os
import threading
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

CLOCK_MARKER_EXPORT_ENV = "VLLM_RLP_ASCEND_CLOCK_MARKER_BRACKETS_PATH"
CLOCK_MARKER_TSV_HEADER = (
    "marker_id\thost_before_ns\trecord_after_ns\thost_after_ns\t"
    "host_pid\thost_tid\t"
    "device_id\tstream_id\tcall_site\treturn_status\n"
)
ACL_EVENT_TIME_LINE = 0x00000008


class AscendRuntime(Protocol):
    def create_timeline_event(self) -> tuple[int, int]: ...

    def record_event(self, event: int, stream: int) -> int: ...

    def synchronize_event(self, event: int) -> int: ...

    def destroy_event(self, event: int) -> int: ...


class CtypesAscendRuntime:
    """Minimal dependency-free AscendCL binding used by the collector."""

    def __init__(self, library_path: str | None = None) -> None:
        self._library = ctypes.CDLL(library_path or "libascendcl.so")
        self._library.aclrtCreateEventWithFlag.argtypes = [
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_uint32,
        ]
        self._library.aclrtCreateEventWithFlag.restype = ctypes.c_int
        self._library.aclrtRecordEvent.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self._library.aclrtRecordEvent.restype = ctypes.c_int
        self._library.aclrtSynchronizeEvent.argtypes = [ctypes.c_void_p]
        self._library.aclrtSynchronizeEvent.restype = ctypes.c_int
        self._library.aclrtDestroyEvent.argtypes = [ctypes.c_void_p]
        self._library.aclrtDestroyEvent.restype = ctypes.c_int

    def create_timeline_event(self) -> tuple[int, int]:
        event = ctypes.c_void_p()
        status = int(
            self._library.aclrtCreateEventWithFlag(
                ctypes.byref(event), ACL_EVENT_TIME_LINE
            )
        )
        return status, int(event.value or 0)

    def record_event(self, event: int, stream: int) -> int:
        return int(
            self._library.aclrtRecordEvent(
                ctypes.c_void_p(event), ctypes.c_void_p(stream)
            )
        )

    def synchronize_event(self, event: int) -> int:
        return int(self._library.aclrtSynchronizeEvent(ctypes.c_void_p(event)))

    def destroy_event(self, event: int) -> int:
        return int(self._library.aclrtDestroyEvent(ctypes.c_void_p(event)))


@dataclass(frozen=True)
class ClockMarkerBracket:
    marker_id: str
    host_before_ns: int
    record_after_ns: int
    host_after_ns: int
    host_pid: int
    host_tid: int
    device_id: int
    stream_id: int | None
    call_site: str
    return_status: int


class AscendClockMarkerCollector:
    """Serialize reusable event markers from a thread with an active context.

    ``stream_handle`` is the native ``aclrtStream`` pointer represented as an
    integer. A value of zero selects the current runtime's default stream.
    ``stream_id`` is optional profiler metadata and is not the pointer value.
    ``host_before_ns``/``record_after_ns`` bracket the record API used for the
    profiler-host→caller-host leg. ``host_before_ns``/``host_after_ns`` bracket
    the device-visible marker used for the caller-host→device leg.
    """

    def __init__(
        self,
        export_path: Path,
        *,
        device_id: int,
        stream_handle: int = 0,
        stream_id: int | None = None,
        call_site: str = "vllm_request_lifecycle_profiler.clock_markers",
        runtime: AscendRuntime | None = None,
        time_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        self._lock = threading.Lock()
        self._sequence = 0
        self._event: int | None = None
        self._fd = -1
        if device_id < 0:
            raise ValueError("device_id must be non-negative")
        if stream_handle < 0:
            raise ValueError("stream_handle must be non-negative")
        if stream_id is not None and stream_id < 0:
            raise ValueError("stream_id must be non-negative")
        _validate_tsv_field(call_site, "call_site")
        self.export_path = Path(export_path)
        self.device_id = int(device_id)
        self.stream_handle = int(stream_handle)
        self.stream_id = None if stream_id is None else int(stream_id)
        self.call_site = call_site
        self._runtime = runtime or CtypesAscendRuntime()
        self._time_ns = time_ns

        status, event = self._runtime.create_timeline_event()
        if status != 0 or event == 0:
            raise RuntimeError(f"aclrtCreateEventWithFlag failed with status {status}")
        self._event = event
        try:
            self.export_path.parent.mkdir(parents=True, exist_ok=True)
            self._fd = os.open(
                self.export_path,
                os.O_CREAT | os.O_APPEND | os.O_WRONLY,
                0o644,
            )
            self._ensure_header()
        except Exception:
            self._runtime.destroy_event(event)
            self._event = None
            raise

    @classmethod
    def from_env(
        cls,
        *,
        device_id: int,
        stream_handle: int = 0,
        stream_id: int | None = None,
        env: Mapping[str, str] | None = None,
        **kwargs: object,
    ) -> AscendClockMarkerCollector | None:
        source = os.environ if env is None else env
        raw_path = source.get(CLOCK_MARKER_EXPORT_ENV, "").strip()
        if not raw_path:
            return None
        return cls(
            Path(raw_path),
            device_id=device_id,
            stream_handle=stream_handle,
            stream_id=stream_id,
            **kwargs,
        )

    def record(self, marker_id: str | None = None) -> ClockMarkerBracket:
        with self._lock:
            if self._event is None or self._fd < 0:
                raise RuntimeError("clock marker collector is closed")
            host_pid = os.getpid()
            host_tid = threading.get_native_id()
            if marker_id is None:
                marker_id = f"{host_pid}-{host_tid}-{self._sequence:06d}"
            _validate_tsv_field(marker_id, "marker_id")
            self._sequence += 1

            host_before_ns = int(self._time_ns())
            record_status = self._runtime.record_event(self._event, self.stream_handle)
            record_after_ns = int(self._time_ns())
            sync_status = (
                self._runtime.synchronize_event(self._event)
                if record_status == 0
                else 0
            )
            host_after_ns = int(self._time_ns())
            if not host_before_ns <= record_after_ns <= host_after_ns:
                raise RuntimeError("CLOCK_REALTIME moved backward across clock marker")
            return_status = record_status if record_status != 0 else sync_status
            bracket = ClockMarkerBracket(
                marker_id=marker_id,
                host_before_ns=host_before_ns,
                record_after_ns=record_after_ns,
                host_after_ns=host_after_ns,
                host_pid=host_pid,
                host_tid=host_tid,
                device_id=self.device_id,
                stream_id=self.stream_id,
                call_site=self.call_site,
                return_status=return_status,
            )
            self._write_bracket(bracket)
            return bracket

    def close(self) -> None:
        with self._lock:
            event = self._event
            self._event = None
            fd = self._fd
            self._fd = -1
            destroy_status = 0
            if event is not None:
                destroy_status = self._runtime.destroy_event(event)
            if fd >= 0:
                os.close(fd)
            if destroy_status != 0:
                raise RuntimeError(
                    f"aclrtDestroyEvent failed with status {destroy_status}"
                )

    def __enter__(self) -> AscendClockMarkerCollector:  # noqa: PYI034
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def __del__(self) -> None:
        with suppress(RuntimeError, OSError):
            self.close()

    def _ensure_header(self) -> None:
        fcntl.flock(self._fd, fcntl.LOCK_EX)
        try:
            if os.fstat(self._fd).st_size == 0:
                _write_all(self._fd, CLOCK_MARKER_TSV_HEADER.encode())
        finally:
            fcntl.flock(self._fd, fcntl.LOCK_UN)

    def _write_bracket(self, bracket: ClockMarkerBracket) -> None:
        stream_id = "" if bracket.stream_id is None else str(bracket.stream_id)
        line = (
            f"{bracket.marker_id}\t{bracket.host_before_ns}\t"
            f"{bracket.record_after_ns}\t{bracket.host_after_ns}\t"
            f"{bracket.host_pid}\t{bracket.host_tid}\t"
            f"{bracket.device_id}\t{stream_id}\t{bracket.call_site}\t"
            f"{bracket.return_status}\n"
        ).encode()
        fcntl.flock(self._fd, fcntl.LOCK_EX)
        try:
            _write_all(self._fd, line)
        finally:
            fcntl.flock(self._fd, fcntl.LOCK_UN)


def _write_all(fd: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(fd, payload[offset:])
        if written <= 0:
            raise OSError("short write while exporting clock marker")
        offset += written


def _validate_tsv_field(value: str, field: str) -> None:
    if not value or any(character in value for character in "\t\r\n"):
        raise ValueError(f"{field} must be non-empty and contain no TSV controls")
