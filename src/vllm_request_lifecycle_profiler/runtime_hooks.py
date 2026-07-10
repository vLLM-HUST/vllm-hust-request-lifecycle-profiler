"""Runtime-hook bridge for writing internal lifecycle events.

This module is intentionally dependency-free so vLLM-HUST hook sites can import
it from a project overlay without pulling in benchmark-only code. The bridge
does not monkey-patch runtime internals by itself; it provides the stable JSONL
schema and thread-safe sink that those hook sites should call.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from vllm_request_lifecycle_profiler.trace import LifecycleStage
from vllm_request_lifecycle_profiler.trace import TraceEvent

MetadataValue = bool | float | int | str

TRACE_EXPORT_ENV = "VLLM_RLP_TRACE_EXPORT_PATH"
OBSERVER_NAME = "vllm_runtime_hook"


@dataclass(frozen=True)
class RuntimeTraceConfig:
    export_path: Path | None
    observer: str = OBSERVER_NAME

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> RuntimeTraceConfig:
        source = os.environ if env is None else env
        raw_path = source.get(TRACE_EXPORT_ENV, "").strip()
        return cls(export_path=Path(raw_path) if raw_path else None)

    @property
    def enabled(self) -> bool:
        return self.export_path is not None


class JsonlTraceSink:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write_event(self, event: TraceEvent) -> None:
        payload = trace_event_to_json(event)
        line = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line)


class NullTraceSink:
    def write_event(self, event: TraceEvent) -> None:
        del event


class RuntimeLifecycleHooks:
    def __init__(
        self,
        config: RuntimeTraceConfig,
        sink: JsonlTraceSink | NullTraceSink | None = None,
    ) -> None:
        self.config = config
        if sink is not None:
            self._sink = sink
        elif config.export_path is None:
            self._sink = NullTraceSink()
        else:
            self._sink = JsonlTraceSink(config.export_path)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> RuntimeLifecycleHooks:
        return cls(RuntimeTraceConfig.from_env(env))

    def emit(
        self,
        request_id: str,
        stage: LifecycleStage,
        *,
        timestamp_ms: float | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> TraceEvent:
        event = TraceEvent(
            request_id=str(request_id),
            stage=stage,
            timestamp_ms=_now_ms() if timestamp_ms is None else float(timestamp_ms),
            metadata=_metadata_with_observer(metadata, observer=self.config.observer),
        )
        self._sink.write_event(event)
        return event

    def received(
        self, request_id: str, *, timestamp_ms: float | None = None, **metadata: MetadataValue
    ) -> TraceEvent:
        return self.emit(
            request_id,
            LifecycleStage.RECEIVED,
            timestamp_ms=timestamp_ms,
            metadata=metadata,
        )

    def tokenized(
        self, request_id: str, *, timestamp_ms: float | None = None, **metadata: MetadataValue
    ) -> TraceEvent:
        return self.emit(
            request_id,
            LifecycleStage.TOKENIZED,
            timestamp_ms=timestamp_ms,
            metadata=metadata,
        )

    def queued(
        self, request_id: str, *, timestamp_ms: float | None = None, **metadata: MetadataValue
    ) -> TraceEvent:
        return self.emit(
            request_id,
            LifecycleStage.QUEUED,
            timestamp_ms=timestamp_ms,
            metadata=metadata,
        )

    def scheduled(
        self, request_id: str, *, timestamp_ms: float | None = None, **metadata: MetadataValue
    ) -> TraceEvent:
        return self.emit(
            request_id,
            LifecycleStage.SCHEDULED,
            timestamp_ms=timestamp_ms,
            metadata=metadata,
        )

    def prefill_done(
        self, request_id: str, *, timestamp_ms: float | None = None, **metadata: MetadataValue
    ) -> TraceEvent:
        return self.emit(
            request_id,
            LifecycleStage.PREFILL_DONE,
            timestamp_ms=timestamp_ms,
            metadata=metadata,
        )

    def first_token(
        self, request_id: str, *, timestamp_ms: float | None = None, **metadata: MetadataValue
    ) -> TraceEvent:
        return self.emit(
            request_id,
            LifecycleStage.FIRST_TOKEN,
            timestamp_ms=timestamp_ms,
            metadata=metadata,
        )

    def decode_done(
        self, request_id: str, *, timestamp_ms: float | None = None, **metadata: MetadataValue
    ) -> TraceEvent:
        return self.emit(
            request_id,
            LifecycleStage.DECODE_DONE,
            timestamp_ms=timestamp_ms,
            metadata=metadata,
        )

    def stream_done(
        self, request_id: str, *, timestamp_ms: float | None = None, **metadata: MetadataValue
    ) -> TraceEvent:
        return self.emit(
            request_id,
            LifecycleStage.STREAM_DONE,
            timestamp_ms=timestamp_ms,
            metadata=metadata,
        )

    def cleanup_done(
        self, request_id: str, *, timestamp_ms: float | None = None, **metadata: MetadataValue
    ) -> TraceEvent:
        return self.emit(
            request_id,
            LifecycleStage.CLEANUP_DONE,
            timestamp_ms=timestamp_ms,
            metadata=metadata,
        )


def trace_event_to_json(event: TraceEvent) -> dict[str, object]:
    return {
        "request_id": event.request_id,
        "stage": event.stage.value,
        "timestamp_ms": event.timestamp_ms,
        "metadata": dict(event.metadata or {}),
    }


def _metadata_with_observer(
    metadata: Mapping[str, MetadataValue] | None,
    *,
    observer: str,
) -> dict[str, MetadataValue]:
    result: dict[str, MetadataValue] = {"observer": observer}
    if metadata:
        result.update(dict(metadata))
    return result


def _now_ms() -> float:
    return time.perf_counter() * 1000.0
