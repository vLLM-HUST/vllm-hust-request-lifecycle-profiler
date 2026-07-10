"""Request lifecycle trace primitives and causal bottleneck attribution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class LifecycleStage(str, Enum):
    RECEIVED = "received"
    TOKENIZED = "tokenized"
    QUEUED = "queued"
    SCHEDULED = "scheduled"
    PREFILL_DONE = "prefill_done"
    FIRST_TOKEN = "first_token"
    DECODE_DONE = "decode_done"
    STREAM_DONE = "stream_done"
    CLEANUP_DONE = "cleanup_done"


class BottleneckKind(str, Enum):
    TOKENIZATION = "tokenization"
    QUEUEING = "queueing"
    PREFILL = "prefill"
    DECODE = "decode"
    STREAMING = "streaming"
    CLEANUP = "cleanup"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class TraceEvent:
    request_id: str
    stage: LifecycleStage
    timestamp_ms: float
    metadata: dict[str, float | int | str] | None = None


@dataclass(frozen=True)
class StageSpan:
    name: str
    start_stage: LifecycleStage
    end_stage: LifecycleStage
    duration_ms: float


@dataclass(frozen=True)
class BottleneckAttribution:
    kind: BottleneckKind
    span_name: str
    duration_ms: float
    reason: str


SPAN_DEFINITIONS = (
    ("tokenization", LifecycleStage.RECEIVED, LifecycleStage.TOKENIZED),
    ("queueing", LifecycleStage.QUEUED, LifecycleStage.SCHEDULED),
    ("prefill", LifecycleStage.SCHEDULED, LifecycleStage.FIRST_TOKEN),
    ("decode", LifecycleStage.FIRST_TOKEN, LifecycleStage.DECODE_DONE),
    ("streaming", LifecycleStage.DECODE_DONE, LifecycleStage.STREAM_DONE),
    ("cleanup", LifecycleStage.STREAM_DONE, LifecycleStage.CLEANUP_DONE),
)


def compute_spans(events: Iterable[TraceEvent]) -> list[StageSpan]:
    by_stage: dict[LifecycleStage, TraceEvent] = {}
    for event in sorted(events, key=lambda item: item.timestamp_ms):
        by_stage.setdefault(event.stage, event)

    spans: list[StageSpan] = []
    for name, start, end in SPAN_DEFINITIONS:
        if start not in by_stage or end not in by_stage:
            continue
        duration = by_stage[end].timestamp_ms - by_stage[start].timestamp_ms
        if duration >= 0:
            spans.append(StageSpan(name, start, end, duration))
    return spans


def attribute_bottleneck(
    events: Iterable[TraceEvent],
    *,
    min_duration_ms: float = 1.0,
) -> BottleneckAttribution:
    spans = compute_spans(events)
    if not spans:
        return BottleneckAttribution(
            BottleneckKind.UNKNOWN,
            "missing_spans",
            0.0,
            "no_complete_lifecycle_span",
        )

    worst = max(spans, key=lambda span: span.duration_ms)
    if worst.duration_ms < min_duration_ms:
        return BottleneckAttribution(
            BottleneckKind.UNKNOWN,
            worst.name,
            worst.duration_ms,
            "all_spans_below_threshold",
        )

    mapping = {
        "tokenization": BottleneckKind.TOKENIZATION,
        "queueing": BottleneckKind.QUEUEING,
        "prefill": BottleneckKind.PREFILL,
        "decode": BottleneckKind.DECODE,
        "streaming": BottleneckKind.STREAMING,
        "cleanup": BottleneckKind.CLEANUP,
    }
    return BottleneckAttribution(
        mapping.get(worst.name, BottleneckKind.UNKNOWN),
        worst.name,
        worst.duration_ms,
        f"largest_lifecycle_span:{worst.name}",
    )

