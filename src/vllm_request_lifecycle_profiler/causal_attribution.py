"""Offline evaluator for intervention-linked lifecycle attribution.

Dominant-span localization and causal evidence are intentionally separate
outputs. A long span without a matched control and declared intervention is
never promoted to causal evidence.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from vllm_request_lifecycle_profiler.trace import LifecycleStage
from vllm_request_lifecycle_profiler.trace import TraceEvent
from vllm_request_lifecycle_profiler.trace import attribute_bottleneck
from vllm_request_lifecycle_profiler.trace import compute_spans


SPAN_NAMES = ("tokenization", "queueing", "prefill", "decode", "streaming", "cleanup")


def load_intervention_fixture(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _events(request_id: str, durations: dict[str, float]) -> list[TraceEvent]:
    missing = [name for name in SPAN_NAMES if name not in durations]
    if missing:
        raise ValueError(f"missing fixture durations: {','.join(missing)}")
    if any(float(durations[name]) < 0 for name in SPAN_NAMES):
        raise ValueError("fixture durations must be non-negative")

    timestamp = 0.0
    events = [TraceEvent(request_id, LifecycleStage.RECEIVED, timestamp)]
    timestamp += float(durations["tokenization"])
    events.append(TraceEvent(request_id, LifecycleStage.TOKENIZED, timestamp))
    events.append(TraceEvent(request_id, LifecycleStage.QUEUED, timestamp))
    timestamp += float(durations["queueing"])
    events.append(TraceEvent(request_id, LifecycleStage.SCHEDULED, timestamp))
    timestamp += float(durations["prefill"])
    events.append(TraceEvent(request_id, LifecycleStage.PREFILL_DONE, timestamp))
    events.append(TraceEvent(request_id, LifecycleStage.FIRST_TOKEN, timestamp))
    timestamp += float(durations["decode"])
    events.append(TraceEvent(request_id, LifecycleStage.DECODE_DONE, timestamp))
    timestamp += float(durations["streaming"])
    events.append(TraceEvent(request_id, LifecycleStage.STREAM_DONE, timestamp))
    timestamp += float(durations["cleanup"])
    events.append(TraceEvent(request_id, LifecycleStage.CLEANUP_DONE, timestamp))
    return events


def _span_durations(events: list[TraceEvent]) -> dict[str, float]:
    return {span.name: span.duration_ms for span in compute_spans(events)}


def evaluate_intervention_fixture(
    fixture: dict[str, Any],
    *,
    min_effect_ms: float = 5.0,
    unchanged_tolerance_ms: float = 1e-9,
) -> dict[str, Any]:
    if fixture.get("schema_version") != 1:
        raise ValueError("schema_version must equal 1")
    evidence_label = fixture.get("evidence_label")
    if evidence_label not in {"simulation/model", "replay", "derived-artifact"}:
        raise ValueError("offline fixture must use an offline evidence label")
    cases = fixture.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("fixture requires at least one case")

    rows: list[dict[str, Any]] = []
    for case in cases:
        case_id = str(case["case_id"])
        observed_events = _events(f"{case_id}:observed", dict(case["observed_durations_ms"]))
        localization = attribute_bottleneck(observed_events)
        row: dict[str, Any] = {
            "case_id": case_id,
            "dominant_span_localization": {
                "span": localization.span_name,
                "kind": localization.kind.value,
                "duration_ms": localization.duration_ms,
                "reason": localization.reason,
            },
            "causal_evidence": {
                "status": "localization_only",
                "supported": False,
                "reason": "matched_control_and_intervention_required",
            },
        }

        intervention = case.get("intervention")
        control_durations = case.get("control_durations_ms")
        if intervention is not None and isinstance(control_durations, dict):
            control_events = _events(f"{case_id}:control", dict(control_durations))
            control_spans = _span_durations(control_events)
            observed_spans = _span_durations(observed_events)
            deltas = {
                name: observed_spans[name] - control_spans[name] for name in SPAN_NAMES
            }
            target = str(intervention.get("target_span", ""))
            declared_change = intervention.get("only_intentional_change")
            linkage_complete = (
                bool(intervention.get("intervention_id"))
                and intervention.get("assignment") == "deterministic"
                and declared_change == [target]
                and target in SPAN_NAMES
            )
            non_target_unchanged = all(
                abs(delta) <= unchanged_tolerance_ms
                for name, delta in deltas.items()
                if name != target
            )
            target_effect = deltas.get(target, 0.0) >= min_effect_ms
            supported = linkage_complete and non_target_unchanged and target_effect
            row["causal_evidence"] = {
                "status": (
                    "intervention_supported_offline_fixture"
                    if supported
                    else "intervention_not_supported"
                ),
                "supported": supported,
                "target_span": target,
                "span_deltas_ms": deltas,
                "linkage_complete": linkage_complete,
                "non_target_spans_unchanged": non_target_unchanged,
                "target_effect_above_threshold": target_effect,
            }
        rows.append(row)

    supported_count = sum(bool(row["causal_evidence"]["supported"]) for row in rows)
    return {
        "schema_version": 1,
        "evidence_label": evidence_label,
        "case_count": len(rows),
        "intervention_supported_case_count": supported_count,
        "rows": rows,
        "m0_status": "NOT_M0_PROVEN",
        "evidence_boundary": (
            "The evaluator validates causal logic on an offline fixture only. "
            "The controlled live graph-mode attribution gate remains open."
        ),
    }


__all__ = ["evaluate_intervention_fixture", "load_intervention_fixture"]
