"""Explicit reader for the historical nine-event JSONL format.

Legacy records are development fixtures only. In particular, their
``stream_done`` event is not upgraded to the v1 response/transport boundary.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from pathlib import Path

from vllm_request_lifecycle_profiler.trace import LifecycleStage, TraceEvent

LegacyMetadataValue = bool | float | int | str


def legacy_trace_event_from_json(record: Mapping[str, object]) -> TraceEvent:
    if set(record) != {"request_id", "stage", "timestamp_ms", "metadata"}:
        raise ValueError("legacy trace record has an unexpected field set")
    request_id = record["request_id"]
    stage = record["stage"]
    timestamp_ms = record["timestamp_ms"]
    metadata = record["metadata"]
    if not isinstance(request_id, str):
        raise TypeError("legacy request_id must be text")
    if not isinstance(stage, str):
        raise TypeError("legacy stage must be text")
    if isinstance(timestamp_ms, bool) or not isinstance(timestamp_ms, int | float):
        raise TypeError("legacy timestamp_ms must be numeric")
    if not math.isfinite(timestamp_ms):
        raise ValueError("legacy timestamp_ms must be finite")
    if not isinstance(metadata, dict):
        raise TypeError("legacy metadata must be an object")
    normalized_metadata: dict[str, LegacyMetadataValue] = {}
    for key, value in metadata.items():
        if not isinstance(key, str):
            raise TypeError("legacy metadata keys must be text")
        if not isinstance(value, bool | float | int | str):
            raise TypeError("legacy metadata values must be scalar")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("legacy metadata floats must be finite")
        normalized_metadata[key] = value
    return TraceEvent(
        request_id=request_id,
        stage=LifecycleStage(stage),
        timestamp_ms=float(timestamp_ms),
        metadata=normalized_metadata,
    )


def load_legacy_jsonl(path: Path) -> list[TraceEvent]:
    events: list[TraceEvent] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.endswith("\n"):
                raise ValueError(
                    f"legacy JSONL line {line_number} has no trailing newline"
                )
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"legacy JSONL line {line_number} is invalid JSON"
                ) from exc
            if not isinstance(payload, dict):
                raise TypeError(f"legacy JSONL line {line_number} is not an object")
            events.append(legacy_trace_event_from_json(payload))
    return events


def legacy_trace_events_to_json(
    events: Iterable[TraceEvent],
) -> list[dict[str, object]]:
    return [
        {
            "request_id": event.request_id,
            "stage": event.stage.value,
            "timestamp_ms": event.timestamp_ms,
            "metadata": dict(event.metadata or {}),
        }
        for event in events
    ]
