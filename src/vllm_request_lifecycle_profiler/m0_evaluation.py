"""M0 evaluation pipeline: phase-DAG normalization, critical-path diff,
top-k mechanism ranking with confidence + unexplained residual, and scoring.

This is the development-level evaluator for blind causal localization
(issue #1). It consumes per-request phase vectors and returns a ranked
mechanism list; it does NOT itself run the Team-A custody/reveal protocol.
"""

from __future__ import annotations

import csv
import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

PHASE_ORDER = (
    "tokenization",
    "queueing",
    "prefill",
    "decode",
    "kv_recovery",
    "streaming",
    "cleanup",
)

# issue #1 mechanism vocabulary (mapped to phase names where possible)
MECHANISM_BY_PHASE = {
    "tokenization": "tokenization",
    "queueing": "queueing",
    "prefill": "prefill",
    "decode": "decode",
    "kv_recovery": "restore/wakeup",
    "streaming": "streaming",
    "cleanup": "cleanup",
}


@dataclass(frozen=True)
class RequestPhases:
    request_id: str
    phases: Mapping[str, float] = field(default_factory=dict)

    def total_ms(self) -> float:
        return sum(self.phases.values())


@dataclass(frozen=True)
class MechanismRank:
    mechanism: str
    phase: str
    delta_ms: float
    share_of_total_delta: float


@dataclass(frozen=True)
class EvaluationReport:
    case_id: str
    baseline_count: int
    anomaly_count: int
    per_phase_delta_ms: Mapping[str, float]
    ranking: tuple[MechanismRank, ...]
    total_positive_delta_ms: float
    top1_share: float
    top3_share: float
    unexplained_residual_ms: float
    unexplained_residual_share: float
    ground_truth: str | None
    top1_ok: bool | None
    top3_ok: bool | None
    mrr: float | None
    abstained: bool
    abstain_reason: str | None
    m0_status: str = "NOT_M0_PROVEN"


def load_phase_rows_csv(path: Path) -> list[RequestPhases]:
    """Load per-request phase rows from the runtime_internal_spans.csv shape."""
    rows: list[RequestPhases] = []
    with open(path, newline="", encoding="utf-8") as handle:
        for record in csv.DictReader(handle):
            phases: dict[str, float] = {}
            for name in PHASE_ORDER:
                if name in record and record[name]:
                    try:
                        phases[name] = float(record[name])
                    except ValueError:
                        continue
            rows.append(RequestPhases(request_id=record.get("chain_id", "?"), phases=phases))
    return rows


def phases_from_kv_recovery_and_client(
    kv_recovery_shards: Iterable[Path],
    client_timing: Mapping[str, float],
    *,
    max_requests: int = 200,
) -> list[RequestPhases]:
    """Build per-request phase vectors from kv-recovery shards + client timing.

    kv_recovery_shards: trace.rlp-kv-recovery.*.jsonl (recovery stages).
    client_timing: mapping runtime_request_id -> end-to-end ms (client total_s).
    The kv_recovery phase is the preempt->first_prefill_or_decode span;
    the remaining time is 'decode' (the non-recovery portion of end-to-end).
    """
    recovery_spans: dict[str, float] = {}
    for shard in kv_recovery_shards:
        for line in shard.open(encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("record_type") != "recovery_event":
                continue
            req = event.get("runtime_request_id")
            stage = event.get("stage")
            ts = event.get("timestamp_ns")
            if not req or not stage or not isinstance(ts, int):
                continue
            if stage == "preempt":
                recovery_spans[req] = {"start": ts}
            elif stage == "first_prefill_or_decode" and req in recovery_spans:
                start = recovery_spans[req].get("start")
                if start is not None:
                    recovery_spans[req] = {
                        "start": start,
                        "end": ts,
                        "span_ms": (ts - start) / 1e6,
                    }
    rows: list[RequestPhases] = []
    for req, total_ms in client_timing.items():
        phases: dict[str, float] = {}
        rec = recovery_spans.get(req)
        if rec and "span_ms" in rec:
            span = max(0.0, rec["span_ms"])
            phases["kv_recovery"] = span
            phases["decode"] = max(0.0, total_ms - span)
        else:
            phases["decode"] = total_ms
        rows.append(RequestPhases(request_id=req, phases=phases))
        if len(rows) >= max_requests:
            break
    return rows


def aggregate_phases(rows: Iterable[RequestPhases]) -> dict[str, float]:
    """Per-phase median over requests (robust to outliers)."""
    by_phase: dict[str, list[float]] = {name: [] for name in PHASE_ORDER}
    for row in rows:
        for name in PHASE_ORDER:
            value = row.phases.get(name)
            if value is not None and value >= 0:
                by_phase[name].append(value)
    return {
        name: statistics.median(values) if values else 0.0
        for name, values in by_phase.items()
    }


def diff_phases(
    baseline: Mapping[str, float], anomaly: Mapping[str, float]
) -> dict[str, float]:
    return {name: anomaly.get(name, 0.0) - baseline.get(name, 0.0) for name in PHASE_ORDER}


def rank_mechanisms(deltas: Mapping[str, float]) -> tuple[MechanismRank, ...]:
    positive = sum(max(0.0, v) for v in deltas.values())
    ranked: list[MechanismRank] = []
    for phase in PHASE_ORDER:
        delta = deltas.get(phase, 0.0)
        if delta <= 0:
            continue
        ranked.append(
            MechanismRank(
                mechanism=MECHANISM_BY_PHASE[phase],
                phase=phase,
                delta_ms=delta,
                share_of_total_delta=(delta / positive) if positive > 0 else 0.0,
            )
        )
    ranked.sort(key=lambda item: item.delta_ms, reverse=True)
    return tuple(ranked)


def evaluate_case(
    baseline_rows: Iterable[RequestPhases],
    anomaly_rows: Iterable[RequestPhases],
    *,
    case_id: str,
    ground_truth: str | None = None,
    abstain_threshold_ms: float = 5.0,
    min_dominance_share: float = 0.6,
) -> EvaluationReport:
    baseline_rows = list(baseline_rows)
    anomaly_rows = list(anomaly_rows)
    baseline = aggregate_phases(baseline_rows)
    anomaly = aggregate_phases(anomaly_rows)
    deltas = diff_phases(baseline, anomaly)
    ranking = rank_mechanisms(deltas)
    total_positive = sum(max(0.0, v) for v in deltas.values())

    # abstention rule (issue #1: allow a no_single_root_cause / abstain case)
    abstained = total_positive < abstain_threshold_ms
    abstain_reason = None
    if not abstained and ranking and ranking[0].share_of_total_delta < min_dominance_share:
        abstained = True
        abstain_reason = "no_single_root_cause"
    if abstained and abstain_reason is None:
        abstain_reason = "insufficient_evidence"
    if abstained:
        ranking = tuple()

    top1_share = ranking[0].share_of_total_delta if ranking else 0.0
    top3_share = sum(r.share_of_total_delta for r in ranking[:3])
    residual_ms = total_positive - (ranking[0].delta_ms if ranking else 0.0)
    residual_share = residual_ms / total_positive if total_positive > 0 else 0.0

    top1_ok = top3_ok = mrr = None
    if not abstained and ground_truth is not None:
        names = [r.mechanism for r in ranking]
        top1_ok = bool(names and names[0] == ground_truth)
        top3_ok = ground_truth in names[:3]
        rank = names.index(ground_truth) + 1 if ground_truth in names else None
        mrr = 1.0 / rank if rank is not None else 0.0

    return EvaluationReport(
        case_id=case_id,
        baseline_count=len(baseline_rows),
        anomaly_count=len(anomaly_rows),
        per_phase_delta_ms=deltas,
        ranking=ranking,
        total_positive_delta_ms=total_positive,
        top1_share=top1_share,
        top3_share=top3_share,
        unexplained_residual_ms=residual_ms,
        unexplained_residual_share=residual_share,
        ground_truth=ground_truth,
        top1_ok=top1_ok,
        top3_ok=top3_ok,
        mrr=mrr,
        abstained=abstained,
        abstain_reason=abstain_reason,
    )


def report_to_dict(report: EvaluationReport) -> dict[str, Any]:
    return {
        "case_id": report.case_id,
        "baseline_count": report.baseline_count,
        "anomaly_count": report.anomaly_count,
        "per_phase_delta_ms": report.per_phase_delta_ms,
        "ranking": [
            {
                "mechanism": r.mechanism,
                "phase": r.phase,
                "delta_ms": round(r.delta_ms, 3),
                "share": round(r.share_of_total_delta, 4),
            }
            for r in report.ranking
        ],
        "total_positive_delta_ms": round(report.total_positive_delta_ms, 3),
        "top1_share": round(report.top1_share, 4),
        "top3_share": round(report.top3_share, 4),
        "unexplained_residual_ms": round(report.unexplained_residual_ms, 3),
        "unexplained_residual_share": round(report.unexplained_residual_share, 4),
        "ground_truth": report.ground_truth,
        "top1_ok": report.top1_ok,
        "top3_ok": report.top3_ok,
        "mrr": report.mrr,
        "abstained": report.abstained,
        "abstain_reason": report.abstain_reason,
        "m0_status": report.m0_status,
    }


__all__ = [
    "PHASE_ORDER",
    "RequestPhases",
    "MechanismRank",
    "EvaluationReport",
    "load_phase_rows_csv",
    "phases_from_kv_recovery_and_client",
    "aggregate_phases",
    "diff_phases",
    "rank_mechanisms",
    "evaluate_case",
    "report_to_dict",
]
