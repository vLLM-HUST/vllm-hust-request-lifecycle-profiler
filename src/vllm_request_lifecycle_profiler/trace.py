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
    KV_PRESSURE = "kv_pressure"
    STREAMING = "streaming"
    CLEANUP = "cleanup"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class TraceEvent:
    request_id: str
    stage: LifecycleStage
    timestamp_ms: float
    metadata: dict[str, bool | float | int | str] | None = None


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


@dataclass(frozen=True)
class SchemaCoverage:
    request_id: str
    observed_stages: tuple[LifecycleStage, ...]
    missing_stages: tuple[LifecycleStage, ...]
    complete_span_names: tuple[str, ...]
    missing_span_names: tuple[str, ...]
    missing_event_rate: float


@dataclass(frozen=True)
class FaultInjectionScenario:
    name: str
    expected_bottleneck: BottleneckKind
    events: tuple[TraceEvent, ...]


@dataclass(frozen=True)
class AttributionMatrix:
    scenario_count: int
    correct_count: int
    false_positive_count: int
    false_negative_count: int
    accuracy: float
    rows: tuple[dict[str, str | float | bool], ...]


SPAN_DEFINITIONS = (
    ("tokenization", LifecycleStage.RECEIVED, LifecycleStage.TOKENIZED),
    ("queueing", LifecycleStage.QUEUED, LifecycleStage.SCHEDULED),
    ("prefill", LifecycleStage.SCHEDULED, LifecycleStage.FIRST_TOKEN),
    ("decode", LifecycleStage.FIRST_TOKEN, LifecycleStage.DECODE_DONE),
    ("streaming", LifecycleStage.DECODE_DONE, LifecycleStage.STREAM_DONE),
    ("cleanup", LifecycleStage.STREAM_DONE, LifecycleStage.CLEANUP_DONE),
)

REQUIRED_SCHEMA_STAGES = tuple(LifecycleStage)

SPAN_TO_BOTTLENECK = {
    "tokenization": BottleneckKind.TOKENIZATION,
    "queueing": BottleneckKind.QUEUEING,
    "prefill": BottleneckKind.PREFILL,
    "decode": BottleneckKind.DECODE,
    "streaming": BottleneckKind.STREAMING,
    "cleanup": BottleneckKind.CLEANUP,
}


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


def evaluate_schema_coverage(events: Iterable[TraceEvent]) -> SchemaCoverage:
    ordered = sorted(events, key=lambda item: item.timestamp_ms)
    request_id = ordered[0].request_id if ordered else ""
    observed = tuple(dict.fromkeys(event.stage for event in ordered))
    observed_set = set(observed)
    missing_stages = tuple(stage for stage in REQUIRED_SCHEMA_STAGES if stage not in observed_set)

    complete_spans = compute_spans(ordered)
    complete_span_names = tuple(span.name for span in complete_spans)
    complete_span_set = set(complete_span_names)
    missing_span_names = tuple(
        name for name, _, _ in SPAN_DEFINITIONS if name not in complete_span_set
    )
    missing_event_rate = len(missing_stages) / len(REQUIRED_SCHEMA_STAGES)
    return SchemaCoverage(
        request_id=request_id,
        observed_stages=observed,
        missing_stages=missing_stages,
        complete_span_names=complete_span_names,
        missing_span_names=missing_span_names,
        missing_event_rate=missing_event_rate,
    )


def _metadata_indicates_kv_pressure(events: Iterable[TraceEvent]) -> bool:
    for event in events:
        metadata = event.metadata or {}
        if metadata.get("kv_pressure") is True:
            return True
        pressure_ratio = metadata.get("kv_cache_pressure_ratio")
        if isinstance(pressure_ratio, int | float) and pressure_ratio >= 0.9:
            return True
    return False


def attribute_bottleneck(
    events: Iterable[TraceEvent],
    *,
    min_duration_ms: float = 1.0,
) -> BottleneckAttribution:
    event_list = list(events)
    spans = compute_spans(event_list)
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

    if _metadata_indicates_kv_pressure(event_list) and worst.name in {"queueing", "prefill"}:
        return BottleneckAttribution(
            BottleneckKind.KV_PRESSURE,
            worst.name,
            worst.duration_ms,
            f"kv_pressure_marker_on_largest_span:{worst.name}",
        )

    return BottleneckAttribution(
        SPAN_TO_BOTTLENECK.get(worst.name, BottleneckKind.UNKNOWN),
        worst.name,
        worst.duration_ms,
        f"largest_lifecycle_span:{worst.name}",
    )


def synthetic_fault_scenarios() -> tuple[FaultInjectionScenario, ...]:
    """Return deterministic no-NPU fault traces with known ground truth."""

    def events_for(
        name: str,
        durations: dict[str, float],
        *,
        expected: BottleneckKind,
        metadata: dict[str, bool | float | int | str] | None = None,
    ) -> FaultInjectionScenario:
        timestamp = 0.0
        events = [TraceEvent(name, LifecycleStage.RECEIVED, timestamp)]
        timestamp += durations.get("tokenization", 1.0)
        events.append(TraceEvent(name, LifecycleStage.TOKENIZED, timestamp))
        timestamp += durations.get("admission_gap", 0.1)
        events.append(TraceEvent(name, LifecycleStage.QUEUED, timestamp))
        timestamp += durations.get("queueing", 1.0)
        events.append(TraceEvent(name, LifecycleStage.SCHEDULED, timestamp, metadata))
        prefill_duration = durations.get("prefill", 1.0)
        timestamp += prefill_duration
        events.append(TraceEvent(name, LifecycleStage.PREFILL_DONE, timestamp, metadata))
        events.append(TraceEvent(name, LifecycleStage.FIRST_TOKEN, timestamp, metadata))
        timestamp += durations.get("decode", 1.0)
        events.append(TraceEvent(name, LifecycleStage.DECODE_DONE, timestamp))
        timestamp += durations.get("streaming", 1.0)
        events.append(TraceEvent(name, LifecycleStage.STREAM_DONE, timestamp))
        timestamp += durations.get("cleanup", 1.0)
        events.append(TraceEvent(name, LifecycleStage.CLEANUP_DONE, timestamp))
        return FaultInjectionScenario(name, expected, tuple(events))

    baseline = {
        "tokenization": 2.0,
        "queueing": 3.0,
        "prefill": 4.0,
        "decode": 5.0,
        "streaming": 2.0,
        "cleanup": 1.0,
    }
    return (
        events_for(
            "tokenizer_slow_path",
            baseline | {"tokenization": 80.0},
            expected=BottleneckKind.TOKENIZATION,
        ),
        events_for(
            "queue_surge",
            baseline | {"queueing": 95.0},
            expected=BottleneckKind.QUEUEING,
        ),
        events_for(
            "prefill_long_prompt",
            baseline | {"prefill": 120.0},
            expected=BottleneckKind.PREFILL,
        ),
        events_for(
            "decode_heavy_output",
            baseline | {"decode": 140.0},
            expected=BottleneckKind.DECODE,
        ),
        events_for(
            "kv_pressure_boundary",
            baseline | {"prefill": 90.0},
            expected=BottleneckKind.KV_PRESSURE,
            metadata={"kv_pressure": True, "kv_cache_pressure_ratio": 0.97},
        ),
        events_for(
            "streaming_backpressure",
            baseline | {"streaming": 110.0},
            expected=BottleneckKind.STREAMING,
        ),
        events_for(
            "cleanup_stall",
            baseline | {"cleanup": 100.0},
            expected=BottleneckKind.CLEANUP,
        ),
    )


def evaluate_fault_injection_matrix(
    scenarios: Iterable[FaultInjectionScenario],
    *,
    min_duration_ms: float = 1.0,
) -> AttributionMatrix:
    rows: list[dict[str, str | float | bool]] = []
    correct = 0
    false_positive = 0
    false_negative = 0
    for scenario in scenarios:
        attribution = attribute_bottleneck(
            scenario.events,
            min_duration_ms=min_duration_ms,
        )
        is_correct = attribution.kind is scenario.expected_bottleneck
        correct += int(is_correct)
        false_positive += int(not is_correct and attribution.kind is not BottleneckKind.UNKNOWN)
        false_negative += int(not is_correct and attribution.kind is BottleneckKind.UNKNOWN)
        coverage = evaluate_schema_coverage(scenario.events)
        rows.append(
            {
                "scenario": scenario.name,
                "expected": scenario.expected_bottleneck.value,
                "observed": attribution.kind.value,
                "span": attribution.span_name,
                "duration_ms": attribution.duration_ms,
                "missing_event_rate": coverage.missing_event_rate,
                "correct": is_correct,
            }
        )

    scenario_count = len(rows)
    accuracy = correct / scenario_count if scenario_count else 0.0
    return AttributionMatrix(
        scenario_count=scenario_count,
        correct_count=correct,
        false_positive_count=false_positive,
        false_negative_count=false_negative,
        accuracy=accuracy,
        rows=tuple(rows),
    )
