"""Deterministic, pre-reveal blind-attribution inputs and scoring.

This module deliberately contains no case oracle and performs no opaque-case
access.  It turns one normalized case bundle into the five predeclared views
and scores explicit lifecycle evidence with the frozen pilot rules.
"""

from __future__ import annotations

import json
import math
import os
import random
import statistics
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from itertools import pairwise
from pathlib import Path
from typing import Any

from vllm_request_lifecycle_profiler.runtime_protocol import (
    COMPONENTS,
    DATA_CAPACITY_RECORDS,
    EVENT_COMPONENT_BY_SCOPE,
    EVENT_NAMES,
    SCOPES,
)

CASE_SCHEMA = "request-lifecycle-blind-case/v1"
RESULT_SCHEMA = "request-lifecycle-blind-result/v1"
VIEW_SCHEMA = "request-lifecycle-blind-view/v1"
BOOTSTRAP_SEED = 2026082701
BOOTSTRAP_RESAMPLES = 10_000
MIN_ABSOLUTE_FLOOR_MS = 5.0
MIN_DOMINANCE_SHARE = 0.60
MAX_RESIDUAL_SHARE = 0.40

VIEW_NAMES = (
    "aggregate_metrics",
    "flat_stage_timers",
    "raw_normalized_events",
    "lifecycle_spans_without_causal_ranking",
    "full_lifecycle_dag",
)

_TOP_LEVEL_KEYS = {"schema", "case_id", "pairs"}
_PAIR_KEYS = {"pair_id", "order", "matching", "baseline", "treatment"}
_MATCHING_KEYS = {
    "workload_id",
    "request_order_id",
    "prompt_tokens",
    "output_tokens",
    "concurrency",
    "batch_shape",
}
_OBSERVATION_KEYS = {
    "run_id",
    "configuration_id",
    "clock_model_id",
    "metrics",
    "evidence_status",
    "normalized_events",
    "lifecycle_spans",
    "lifecycle_edges",
    "traceloom_links",
}
_NORMALIZED_EVENT_KEYS = {
    "event_id",
    "trace_id",
    "engine_lifecycle_id",
    "recovery_epoch",
    "request_id",
    "scope",
    "component",
    "event_name",
    "timestamp_ns",
    "clock_domain",
    "evidence_source",
    "support_state",
    "batch_id",
    "step_id",
}
_METRIC_KEYS = {
    "ttft_ms",
    "tpot_ms",
    "latency_ms",
    "throughput_rps",
    "error_count",
}
_EVIDENCE_KEYS = {
    "identity_complete",
    "event_loss_count",
    "clock_ambiguous",
    "configuration_matched",
}
_SPAN_KEYS = {
    "span_id",
    "start_event_id",
    "end_event_id",
    "candidate_id",
    "trace_id",
    "engine_lifecycle_id",
    "recovery_epoch",
    "request_id",
    "owner",
    "clock_domain",
    "evidence_source",
    "support_state",
    "start_ns",
    "end_ns",
    "accounted_duration_ms",
    "batch_id",
    "step_id",
}
_EDGE_KEYS = {"source_span_id", "target_span_id", "kind"}
_LINK_KEYS = {
    "span_id",
    "trace_id",
    "engine_lifecycle_id",
    "recovery_epoch",
    "request_id",
    "batch_id",
    "step_id",
    "tree_id",
    "node_id",
    "occurrence_idx",
    "anchor_id",
    "event_id",
    "runtime_relation_id",
    "runtime_call_id",
    "device_work_id",
    "sync_action_id",
    "graph_event_id",
    "graph_envelope_id",
    "link_kind",
    "owner",
    "clock_domain",
    "evidence_source",
    "support_state",
    "reason",
}
_LINK_KINDS = {
    "request_handoff",
    "batch_membership",
    "execution_support",
    "resource_owner",
}
_EDGE_KINDS = {
    "request_handoff",
    "batch_membership",
    "execution_support",
    "resource_owner",
    "precedes",
}
_SUPPORTED_STATES = {"supported_exact", "supported_deterministic"}
_FORBIDDEN_KEYS = {
    "oracle",
    "ground_truth",
    "fault_name",
    "fault_manifest",
    "injected_pressure",
    "intervention_assignment",
    "salt",
    "answer",
}
_FORBIDDEN_CASE_TOKENS = ("fault", "oracle", "token", "queue", "prefill", "decode")


class CaseValidationError(ValueError):
    """The diagnosis bundle violates the closed pre-reveal contract."""


@dataclass(frozen=True)
class CandidateScore:
    candidate_id: str
    paired_deltas_ms: tuple[float, ...]
    median_delta_ms: float
    iqr_delta_ms: float
    bootstrap_ci95_ms: tuple[float, float]
    positive_delta_share: float
    top1_selection_frequency: float
    span_count: int
    owners: tuple[str, ...]
    edge_kinds: tuple[str, ...]
    traceloom_link_count: int


@dataclass(frozen=True)
class AttributionResult:
    schema: str
    case_id: str
    m0_status: str
    top1: str | None
    top3: tuple[str, ...]
    candidates: tuple[CandidateScore, ...]
    dominance_score: float
    confidence_score: float
    unexplained_residual_share: float
    insufficient_evidence_floor_ms: float
    bootstrap_seed: int
    bootstrap_resamples: int
    abstained: bool
    abstain_reasons: tuple[str, ...]
    proposed_counterfactual: Mapping[str, str] | None
    input_complete: bool
    input_event_loss_count: int


def load_candidate_ids(path: Path) -> tuple[str, ...]:
    payload = _load_json(path)
    if payload.get("schema") != "request-lifecycle-blind-candidates/v1":
        raise CaseValidationError("unsupported candidate vocabulary schema")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise CaseValidationError("candidate vocabulary must be a non-empty list")
    ids = tuple(item.get("id") for item in candidates if isinstance(item, dict))
    if len(ids) != len(candidates) or any(not _bounded_text(value) for value in ids):
        raise CaseValidationError("candidate vocabulary contains an invalid id")
    if len(set(ids)) != len(ids):
        raise CaseValidationError("candidate vocabulary ids must be unique")
    return ids


def load_case_bundle(path: Path, *, candidate_ids: Iterable[str]) -> dict[str, Any]:
    bundle = _load_json(path)
    validate_case_bundle(bundle, candidate_ids=candidate_ids)
    return bundle


def validate_case_bundle(
    bundle: Mapping[str, Any], *, candidate_ids: Iterable[str]
) -> None:
    """Validate a closed, oracle-free diagnosis bundle.

    The validator is intentionally independent of opaque case custody.  It
    checks only the diagnosis-side package and never accepts reveal metadata.
    """

    candidate_ids = tuple(candidate_ids)
    if not candidate_ids or any(not _bounded_text(item) for item in candidate_ids):
        raise CaseValidationError("candidate vocabulary is invalid")
    allowed_candidates = set(candidate_ids)
    if len(allowed_candidates) != len(candidate_ids):
        raise CaseValidationError("candidate vocabulary ids must be unique")
    _reject_forbidden_keys(bundle)
    _exact_keys(bundle, _TOP_LEVEL_KEYS, "bundle")
    if bundle.get("schema") != CASE_SCHEMA:
        raise CaseValidationError(f"schema must be {CASE_SCHEMA}")
    case_id = bundle.get("case_id")
    if not _bounded_text(case_id, limit=64):
        raise CaseValidationError(
            "case_id must be a non-empty string of at most 64 characters"
        )
    if any(token in case_id.lower() for token in _FORBIDDEN_CASE_TOKENS):
        raise CaseValidationError("case_id must be semantically neutral")
    pairs = bundle.get("pairs")
    if (
        not isinstance(pairs, list)
        or len(pairs) < 5
        or len(pairs) > DATA_CAPACITY_RECORDS
    ):
        raise CaseValidationError("a pilot case must contain 5-4096 matched pairs")
    orders = [pair.get("order") for pair in pairs if isinstance(pair, Mapping)]
    if any(order not in {"AB", "BA"} for order in orders) or any(
        left == right for left, right in pairwise(orders)
    ):
        raise CaseValidationError("matched pair order must alternate AB/BA")
    pair_ids: set[str] = set()
    run_ids: set[str] = set()
    for pair_index, pair in enumerate(pairs):
        where = f"pairs[{pair_index}]"
        if not isinstance(pair, Mapping):
            raise CaseValidationError(f"{where} must be an object")
        _exact_keys(pair, _PAIR_KEYS, where)
        pair_id = pair.get("pair_id")
        if not _bounded_text(pair_id, limit=64) or pair_id in pair_ids:
            raise CaseValidationError(f"{where}.pair_id must be bounded and unique")
        pair_ids.add(pair_id)
        if pair.get("order") not in {"AB", "BA"}:
            raise CaseValidationError(f"{where}.order must be AB or BA")
        _validate_matching(pair.get("matching"), f"{where}.matching")
        baseline = _validate_observation(
            pair.get("baseline"), f"{where}.baseline", allowed_candidates, run_ids
        )
        treatment = _validate_observation(
            pair.get("treatment"), f"{where}.treatment", allowed_candidates, run_ids
        )
        if baseline["configuration_id"] != treatment["configuration_id"]:
            raise CaseValidationError(f"{where} has unmatched configuration_id")
        if baseline["clock_model_id"] != treatment["clock_model_id"]:
            raise CaseValidationError(f"{where} has unmatched clock_model_id")


def render_comparison_views(bundle: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Derive the five fair-comparison inputs from one validated source bundle."""

    common = {
        "schema": VIEW_SCHEMA,
        "case_id": bundle["case_id"],
    }
    rendered: dict[str, dict[str, Any]] = {}
    for view_name in VIEW_NAMES:
        view_pairs: list[dict[str, Any]] = []
        for pair in bundle["pairs"]:
            view_pair: dict[str, Any] = {
                "pair_id": pair["pair_id"],
                "order": pair["order"],
            }
            for arm in ("baseline", "treatment"):
                observation = pair[arm]
                base = {
                    "run_id": observation["run_id"],
                    "configuration_id": observation["configuration_id"],
                    "clock_model_id": observation["clock_model_id"],
                    "evidence_status": observation["evidence_status"],
                }
                view_pair["matching"] = pair["matching"]
                if view_name == "aggregate_metrics":
                    base["metrics"] = observation["metrics"]
                elif view_name == "flat_stage_timers":
                    base["stage_timers_ms"] = _stage_totals(
                        observation["lifecycle_spans"]
                    )
                elif view_name == "raw_normalized_events":
                    base["metrics"] = observation["metrics"]
                    base["events"] = observation["normalized_events"]
                elif view_name == "lifecycle_spans_without_causal_ranking":
                    base["metrics"] = observation["metrics"]
                    base["spans"] = observation["lifecycle_spans"]
                else:
                    base["metrics"] = observation["metrics"]
                    base["spans"] = observation["lifecycle_spans"]
                    base["edges"] = observation["lifecycle_edges"]
                    base["traceloom_links"] = observation["traceloom_links"]
                view_pair[arm] = base
            view_pairs.append(view_pair)
        rendered[view_name] = {**common, "view": view_name, "pairs": view_pairs}
    return rendered


def calibrate_noise_floor(total_matched_deltas_ms: Sequence[float]) -> dict[str, float]:
    """Apply the preregistered nearest-rank p95 calibration rule."""

    if len(total_matched_deltas_ms) != 5:
        raise ValueError("formal calibration requires exactly five matched null pairs")
    values: list[float] = []
    for value in total_matched_deltas_ms:
        if not _finite_number(value):
            raise ValueError("calibration deltas must be finite numbers")
        values.append(abs(float(value)))
    values.sort()
    rank = max(1, math.ceil(0.95 * len(values)))
    null_p95 = values[rank - 1]
    return {
        "null_delta_p95_ms": null_p95,
        "insufficient_evidence_floor_ms": max(MIN_ABSOLUTE_FLOOR_MS, null_p95),
    }


def score_case(
    bundle: Mapping[str, Any],
    *,
    candidate_ids: Iterable[str],
    insufficient_evidence_floor_ms: float,
    traceloom_databases: Mapping[str, Path] | None = None,
    bootstrap_seed: int = BOOTSTRAP_SEED,
    bootstrap_resamples: int = BOOTSTRAP_RESAMPLES,
) -> AttributionResult:
    """Score explicit matched lifecycle evidence without consulting an oracle."""

    candidate_ids = _validate_scorer_inputs(
        candidate_ids,
        insufficient_evidence_floor_ms,
        bootstrap_seed,
        bootstrap_resamples,
    )
    validate_case_bundle(bundle, candidate_ids=candidate_ids)
    return _score_validated_case(
        bundle,
        candidate_ids=candidate_ids,
        insufficient_evidence_floor_ms=insufficient_evidence_floor_ms,
        traceloom_databases=traceloom_databases,
        bootstrap_seed=bootstrap_seed,
        bootstrap_resamples=bootstrap_resamples,
    )


def _validate_scorer_inputs(
    candidate_ids: Iterable[str],
    insufficient_evidence_floor_ms: float,
    bootstrap_seed: int,
    bootstrap_resamples: int,
) -> tuple[str, ...]:
    candidate_ids = tuple(candidate_ids)
    if (
        not candidate_ids
        or any(not _bounded_text(candidate) for candidate in candidate_ids)
        or len(set(candidate_ids)) != len(candidate_ids)
        or "insufficient_evidence_or_multi_cause" not in candidate_ids
        or len(candidate_ids) == 1
    ):
        raise ValueError(
            "candidate_ids must be a unique bounded vocabulary with measurable "
            "candidates and the abstention candidate"
        )
    if (
        not _finite_number(insufficient_evidence_floor_ms)
        or insufficient_evidence_floor_ms < 0
    ):
        raise ValueError(
            "insufficient_evidence_floor_ms must be finite and non-negative"
        )
    if bootstrap_seed != BOOTSTRAP_SEED:
        raise ValueError(f"bootstrap_seed is fixed at {BOOTSTRAP_SEED}")
    if bootstrap_resamples != BOOTSTRAP_RESAMPLES:
        raise ValueError(f"bootstrap_resamples is fixed at {BOOTSTRAP_RESAMPLES}")
    return candidate_ids


def _score_validated_case(
    bundle: Mapping[str, Any],
    *,
    candidate_ids: tuple[str, ...],
    insufficient_evidence_floor_ms: float,
    traceloom_databases: Mapping[str, Path] | None,
    bootstrap_seed: int,
    bootstrap_resamples: int,
) -> AttributionResult:
    candidates = tuple(
        candidate
        for candidate in candidate_ids
        if candidate != "insufficient_evidence_or_multi_cause"
    )
    pair_deltas: dict[str, list[float]] = {candidate: [] for candidate in candidates}
    evidence_reasons: set[str] = set()
    candidate_evidence: dict[str, dict[str, Any]] = {
        candidate: {
            "span_ids": set(),
            "owners": set(),
            "edge_kinds": set(),
            "traceloom_link_count": 0,
        }
        for candidate in candidates
    }
    loss_count = 0
    for pair in bundle["pairs"]:
        for arm in ("baseline", "treatment"):
            observation = pair[arm]
            status = observation["evidence_status"]
            loss_count += status["event_loss_count"]
            if not status["identity_complete"]:
                evidence_reasons.add("incomplete_identity")
            if status["event_loss_count"]:
                evidence_reasons.add("event_loss")
            if status["clock_ambiguous"]:
                evidence_reasons.add("clock_ambiguity")
            if not status["configuration_matched"]:
                evidence_reasons.add("unmatched_configuration")
            for span in observation["lifecycle_spans"]:
                if span["support_state"] not in _SUPPORTED_STATES:
                    evidence_reasons.add("unsupported_lifecycle_span")
            for event in observation["normalized_events"]:
                if event["support_state"] not in _SUPPORTED_STATES:
                    evidence_reasons.add("unsupported_normalized_event")
            for link in observation["traceloom_links"]:
                if link["support_state"] not in _SUPPORTED_STATES:
                    evidence_reasons.add("unsupported_or_ambiguous_traceloom_link")
            _verify_traceloom_evidence(
                observation, traceloom_databases, evidence_reasons
            )
            _collect_candidate_evidence(
                observation, candidate_evidence, evidence_reasons
            )
        baseline = _candidate_totals(pair["baseline"]["lifecycle_spans"])
        treatment = _candidate_totals(pair["treatment"]["lifecycle_spans"])
        for candidate in candidates:
            pair_deltas[candidate].append(
                treatment.get(candidate, 0.0) - baseline.get(candidate, 0.0)
            )

    medians = {
        candidate: statistics.median(values)
        for candidate, values in pair_deltas.items()
    }
    positive_total = sum(max(0.0, value) for value in medians.values())
    ranked_ids = sorted(candidates, key=lambda item: (-medians[item], item))
    ranked_ids = [candidate for candidate in ranked_ids if medians[candidate] > 0]
    top = ranked_ids[0] if ranked_ids else None
    dominance = (
        max(0.0, medians.get(top, 0.0)) / positive_total
        if top and positive_total
        else 0.0
    )
    residual = 1.0 - dominance if positive_total else 1.0

    bootstrap = _bootstrap(pair_deltas, candidates, bootstrap_seed, bootstrap_resamples)
    scores: list[CandidateScore] = []
    for candidate in ranked_ids:
        values = pair_deltas[candidate]
        lower, upper = _percentile_interval(bootstrap["medians"][candidate])
        scores.append(
            CandidateScore(
                candidate_id=candidate,
                paired_deltas_ms=tuple(values),
                median_delta_ms=medians[candidate],
                iqr_delta_ms=_iqr(values),
                bootstrap_ci95_ms=(lower, upper),
                positive_delta_share=medians[candidate] / positive_total,
                top1_selection_frequency=bootstrap["top1_counts"][candidate]
                / bootstrap_resamples,
                span_count=len(candidate_evidence[candidate]["span_ids"]),
                owners=tuple(sorted(candidate_evidence[candidate]["owners"])),
                edge_kinds=tuple(sorted(candidate_evidence[candidate]["edge_kinds"])),
                traceloom_link_count=candidate_evidence[candidate][
                    "traceloom_link_count"
                ],
            )
        )

    reasons = set(evidence_reasons)
    if positive_total < insufficient_evidence_floor_ms:
        reasons.add("below_insufficient_evidence_floor")
    if not top:
        reasons.add("no_positive_candidate_delta")
    if dominance < MIN_DOMINANCE_SHARE:
        reasons.add("no_single_root_cause")
    if residual > MAX_RESIDUAL_SHARE + 1e-12:
        reasons.add("excess_unexplained_residual")
    if (
        scores
        and scores[0].bootstrap_ci95_ms[0] <= 0.0 <= scores[0].bootstrap_ci95_ms[1]
    ):
        reasons.add("top_candidate_bootstrap_ci_crosses_zero")

    abstained = bool(reasons)
    selection_frequency = scores[0].top1_selection_frequency if scores else 0.0
    return AttributionResult(
        schema=RESULT_SCHEMA,
        case_id=bundle["case_id"],
        m0_status="NOT_M0_PROVEN",
        top1=None if abstained else top,
        top3=tuple(ranked_ids[:3]),
        candidates=tuple(scores),
        dominance_score=dominance,
        confidence_score=min(dominance, selection_frequency),
        unexplained_residual_share=residual,
        insufficient_evidence_floor_ms=float(insufficient_evidence_floor_ms),
        bootstrap_seed=bootstrap_seed,
        bootstrap_resamples=bootstrap_resamples,
        abstained=abstained,
        abstain_reasons=tuple(sorted(reasons)),
        proposed_counterfactual=(
            None
            if abstained or top is None
            else {"candidate_id": top, "constraint": "change_only_predicted_mechanism"}
        ),
        input_complete=not evidence_reasons,
        input_event_loss_count=loss_count,
    )


def timed_score_case(
    bundle: Mapping[str, Any],
    *,
    method: str,
    candidate_ids: Iterable[str],
    insufficient_evidence_floor_ms: float,
    traceloom_databases: Mapping[str, Path] | None = None,
    bootstrap_seed: int = BOOTSTRAP_SEED,
    bootstrap_resamples: int = BOOTSTRAP_RESAMPLES,
) -> dict[str, Any]:
    """Return a result plus the required actual diagnosis timing fields."""

    if method != "full_lifecycle_dag":
        raise ValueError("the automated DAG scorer may only label full_lifecycle_dag")
    candidate_ids = _validate_scorer_inputs(
        candidate_ids,
        insufficient_evidence_floor_ms,
        bootstrap_seed,
        bootstrap_resamples,
    )
    validate_case_bundle(bundle, candidate_ids=candidate_ids)
    started_at = datetime.now(timezone.utc)
    started_ns = time.perf_counter_ns()
    result = _score_validated_case(
        bundle,
        candidate_ids=candidate_ids,
        insufficient_evidence_floor_ms=insufficient_evidence_floor_ms,
        traceloom_databases=traceloom_databases,
        bootstrap_seed=bootstrap_seed,
        bootstrap_resamples=bootstrap_resamples,
    )
    elapsed_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
    ended_at = datetime.now(timezone.utc)
    payload = asdict(result)
    payload.update(
        {
            "method": method,
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "time_to_localize_ms": elapsed_ms,
            "automated_wall_clock_ms": elapsed_ms,
        }
    )
    return payload


def write_locked_result(path: Path, payload: Mapping[str, Any]) -> None:
    """Create a pre-reveal result exactly once; never overwrite it."""

    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, allow_nan=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def write_locked_method_result(
    path: Path, payload: Mapping[str, Any], *, candidate_ids: Iterable[str]
) -> None:
    """Validate and exclusively create one diagnosis-method result."""

    required = {
        "schema",
        "case_id",
        "method",
        "m0_status",
        "top1",
        "top3",
        "candidates",
        "dominance_score",
        "confidence_score",
        "unexplained_residual_share",
        "insufficient_evidence_floor_ms",
        "bootstrap_seed",
        "bootstrap_resamples",
        "abstained",
        "abstain_reasons",
        "proposed_counterfactual",
        "input_complete",
        "input_event_loss_count",
        "started_at",
        "ended_at",
        "time_to_localize_ms",
        "automated_wall_clock_ms",
    }
    _exact_keys(payload, required, "method_result")
    if payload["schema"] != RESULT_SCHEMA:
        raise CaseValidationError(f"method result schema must be {RESULT_SCHEMA}")
    if not _bounded_text(payload["case_id"], limit=64):
        raise CaseValidationError("method_result.case_id must be bounded")
    if not isinstance(payload["method"], str) or payload["method"] not in VIEW_NAMES:
        raise CaseValidationError("method result names an unknown comparison method")
    if payload["m0_status"] != "NOT_M0_PROVEN":
        raise CaseValidationError("development result must remain NOT_M0_PROVEN")
    candidate_ids = tuple(candidate_ids)
    if not candidate_ids or any(not _bounded_text(item) for item in candidate_ids):
        raise CaseValidationError("method result candidate vocabulary is invalid")
    allowed_candidates = set(candidate_ids)
    if len(allowed_candidates) != len(candidate_ids):
        raise CaseValidationError("method result candidate vocabulary is duplicated")
    measurable_candidates = allowed_candidates - {
        "insufficient_evidence_or_multi_cause"
    }
    top1 = payload["top1"]
    top3 = payload["top3"]
    if top1 is not None and (
        not _bounded_text(top1) or top1 not in measurable_candidates
    ):
        raise CaseValidationError(
            "method_result.top1 is outside the candidate vocabulary"
        )
    if (
        not isinstance(top3, (list, tuple))
        or len(top3) > 3
        or any(
            not _bounded_text(candidate) or candidate not in measurable_candidates
            for candidate in top3
        )
        or len(set(top3)) != len(top3)
    ):
        raise CaseValidationError("method_result.top3 is invalid")
    candidate_scores = payload["candidates"]
    if not isinstance(candidate_scores, (list, tuple)):
        raise CaseValidationError("method_result.candidates must be a list")
    score_ids: list[str] = []
    for index, score in enumerate(candidate_scores):
        score_ids.append(_validate_candidate_score(score, index, measurable_candidates))
    if len(set(score_ids)) != len(score_ids):
        raise CaseValidationError("method_result.candidates contains duplicate ids")
    if tuple(score_ids[:3]) != tuple(top3):
        raise CaseValidationError("method_result.top3 must match ranked candidates")
    delta_counts = {len(score["paired_deltas_ms"]) for score in candidate_scores}
    if len(delta_counts) > 1:
        raise CaseValidationError(
            "method_result candidates must use the same matched-pair count"
        )
    if not isinstance(payload["abstained"], bool):
        raise CaseValidationError("method_result.abstained must be boolean")
    if payload["abstained"] and payload["top1"] is not None:
        raise CaseValidationError("an abstained result cannot publish a top1 decision")
    if not payload["abstained"] and not _bounded_text(payload["top1"]):
        raise CaseValidationError("a non-abstained result requires top1")
    if not payload["abstained"] and (not score_ids or top1 != score_ids[0]):
        raise CaseValidationError("method_result.top1 must match the first candidate")
    for key in (
        "dominance_score",
        "confidence_score",
        "unexplained_residual_share",
    ):
        value = payload[key]
        if not _finite_number(value) or not 0 <= value <= 1:
            raise CaseValidationError(f"method_result.{key} must be in [0, 1]")
    dominance = payload["dominance_score"]
    residual = payload["unexplained_residual_share"]
    if not math.isclose(dominance + residual, 1.0, abs_tol=1e-9):
        raise CaseValidationError(
            "method_result dominance and residual shares must sum to one"
        )
    if payload["confidence_score"] > dominance + 1e-12:
        raise CaseValidationError("method_result confidence cannot exceed dominance")
    if candidate_scores:
        shares = [score["positive_delta_share"] for score in candidate_scores]
        if not math.isclose(sum(shares), 1.0, abs_tol=1e-9):
            raise CaseValidationError("method_result candidate shares must sum to one")
        if not math.isclose(shares[0], dominance, abs_tol=1e-9):
            raise CaseValidationError(
                "method_result dominance must equal the top candidate share"
            )
    elif dominance != 0 or residual != 1:
        raise CaseValidationError(
            "method_result without candidates must have zero dominance"
        )
    floor = payload["insufficient_evidence_floor_ms"]
    if not _finite_number(floor) or floor < 0:
        raise CaseValidationError(
            "method_result.insufficient_evidence_floor_ms must be non-negative"
        )
    if payload["bootstrap_seed"] != BOOTSTRAP_SEED:
        raise CaseValidationError("method_result.bootstrap_seed changed")
    if payload["bootstrap_resamples"] != BOOTSTRAP_RESAMPLES:
        raise CaseValidationError("method_result.bootstrap_resamples changed")
    reasons = payload["abstain_reasons"]
    if not isinstance(reasons, (list, tuple)) or any(
        not _bounded_text(reason, limit=128) for reason in reasons
    ):
        raise CaseValidationError("method_result.abstain_reasons is invalid")
    if len(set(reasons)) != len(reasons):
        raise CaseValidationError("method_result.abstain_reasons contains duplicates")
    if payload["abstained"] != bool(reasons):
        raise CaseValidationError(
            "method_result abstention and reasons must be mutually consistent"
        )
    counterfactual = payload["proposed_counterfactual"]
    if counterfactual is not None:
        _exact_keys(
            counterfactual,
            {"candidate_id", "constraint"},
            "method_result.proposed_counterfactual",
        )
        if (
            counterfactual["candidate_id"] != top1
            or counterfactual["constraint"] != "change_only_predicted_mechanism"
        ):
            raise CaseValidationError("method_result counterfactual is inconsistent")
    if payload["abstained"] and counterfactual is not None:
        raise CaseValidationError("an abstained result cannot propose a counterfactual")
    if not payload["abstained"] and counterfactual is None:
        raise CaseValidationError(
            "a non-abstained result requires a rank-one counterfactual"
        )
    if not isinstance(payload["input_complete"], bool):
        raise CaseValidationError("method_result.input_complete must be boolean")
    loss_count = payload["input_event_loss_count"]
    if (
        isinstance(loss_count, bool)
        or not isinstance(loss_count, int)
        or loss_count < 0
    ):
        raise CaseValidationError(
            "method_result.input_event_loss_count must be a non-negative integer"
        )
    if loss_count and payload["input_complete"]:
        raise CaseValidationError("a lossy method result cannot claim complete input")
    for key in ("started_at", "ended_at"):
        if not _bounded_text(payload[key]):
            raise CaseValidationError(f"method_result.{key} must be bounded")
    for key in ("time_to_localize_ms", "automated_wall_clock_ms"):
        value = payload[key]
        if not _finite_number(value) or value < 0:
            raise CaseValidationError(f"method_result.{key} must be non-negative")
    try:
        started_at = datetime.fromisoformat(payload["started_at"])
        ended_at = datetime.fromisoformat(payload["ended_at"])
    except ValueError as exc:
        raise CaseValidationError("method result timestamps must be ISO-8601") from exc
    if started_at.tzinfo is None or ended_at.tzinfo is None or ended_at < started_at:
        raise CaseValidationError(
            "method result timestamps are unordered or lack timezone"
        )
    write_locked_result(path, payload)


def _validate_candidate_score(
    score: Any, index: int, allowed_candidates: set[str]
) -> str:
    where = f"method_result.candidates[{index}]"
    if not isinstance(score, Mapping):
        raise CaseValidationError(f"{where} must be an object")
    keys = {
        "candidate_id",
        "paired_deltas_ms",
        "median_delta_ms",
        "iqr_delta_ms",
        "bootstrap_ci95_ms",
        "positive_delta_share",
        "top1_selection_frequency",
        "span_count",
        "owners",
        "edge_kinds",
        "traceloom_link_count",
    }
    _exact_keys(score, keys, where)
    candidate = score["candidate_id"]
    if not _bounded_text(candidate) or candidate not in allowed_candidates:
        raise CaseValidationError(f"{where}.candidate_id is outside the vocabulary")
    deltas = score["paired_deltas_ms"]
    if (
        not isinstance(deltas, (list, tuple))
        or len(deltas) < 5
        or any(not _finite_number(value) for value in deltas)
    ):
        raise CaseValidationError(f"{where}.paired_deltas_ms is invalid")
    interval = score["bootstrap_ci95_ms"]
    if (
        not isinstance(interval, (list, tuple))
        or len(interval) != 2
        or any(not _finite_number(value) for value in interval)
        or interval[1] < interval[0]
    ):
        raise CaseValidationError(f"{where}.bootstrap_ci95_ms is invalid")
    for key in ("median_delta_ms", "iqr_delta_ms"):
        if not _finite_number(score[key]):
            raise CaseValidationError(f"{where}.{key} must be finite")
    if score["median_delta_ms"] <= 0:
        raise CaseValidationError(f"{where}.median_delta_ms must be positive")
    if score["iqr_delta_ms"] < 0:
        raise CaseValidationError(f"{where}.iqr_delta_ms must be non-negative")
    if not math.isclose(
        float(score["median_delta_ms"]), statistics.median(deltas), abs_tol=1e-9
    ):
        raise CaseValidationError(f"{where}.median_delta_ms does not match deltas")
    if not math.isclose(float(score["iqr_delta_ms"]), _iqr(deltas), abs_tol=1e-9):
        raise CaseValidationError(f"{where}.iqr_delta_ms does not match deltas")
    for key in ("positive_delta_share", "top1_selection_frequency"):
        if not _finite_number(score[key]) or not 0 <= score[key] <= 1:
            raise CaseValidationError(f"{where}.{key} must be in [0, 1]")
    for key in ("span_count", "traceloom_link_count"):
        if (
            isinstance(score[key], bool)
            or not isinstance(score[key], int)
            or score[key] < 0
        ):
            raise CaseValidationError(f"{where}.{key} must be non-negative integer")
    if score["span_count"] == 0:
        raise CaseValidationError(f"{where}.span_count must be positive")
    for key in ("owners", "edge_kinds"):
        values = score[key]
        if not isinstance(values, (list, tuple)) or any(
            not _bounded_text(value) for value in values
        ):
            raise CaseValidationError(f"{where}.{key} is invalid")
        if len(set(values)) != len(values):
            raise CaseValidationError(f"{where}.{key} contains duplicates")
    if not score["owners"]:
        raise CaseValidationError(f"{where}.owners must not be empty")
    if any(kind not in _EDGE_KINDS for kind in score["edge_kinds"]):
        raise CaseValidationError(f"{where}.edge_kinds is unsupported")
    if (
        not (set(score["edge_kinds"]) - {"precedes"})
        and not score["traceloom_link_count"]
    ):
        raise CaseValidationError(f"{where} lacks causal or ownership evidence")
    return candidate


def _collect_candidate_evidence(
    observation: Mapping[str, Any],
    evidence: dict[str, dict[str, Any]],
    reasons: set[str],
) -> None:
    spans = {span["span_id"]: span for span in observation["lifecycle_spans"]}
    incident_edges: dict[str, set[str]] = {span_id: set() for span_id in spans}
    supported_links: dict[str, int] = {span_id: 0 for span_id in spans}
    for edge in observation["lifecycle_edges"]:
        incident_edges[edge["source_span_id"]].add(edge["kind"])
        incident_edges[edge["target_span_id"]].add(edge["kind"])
    for link in observation["traceloom_links"]:
        if link["support_state"] in _SUPPORTED_STATES:
            supported_links[link["span_id"]] += 1
    for span_id, span in spans.items():
        candidate = span["candidate_id"]
        packet = evidence[candidate]
        packet["span_ids"].add(f"{observation['run_id']}\0{span_id}")
        packet["owners"].add(span["owner"])
        packet["edge_kinds"].update(incident_edges[span_id])
        packet["traceloom_link_count"] += supported_links[span_id]
        if (
            not (incident_edges[span_id] - {"precedes"})
            and not supported_links[span_id]
        ):
            reasons.add("unlinked_lifecycle_span")


def _verify_traceloom_evidence(
    observation: Mapping[str, Any],
    databases: Mapping[str, Path] | None,
    reasons: set[str],
) -> None:
    links = observation["traceloom_links"]
    if not links:
        return
    database = None if databases is None else databases.get(observation["run_id"])
    if database is None:
        reasons.add("traceloom_evidence_not_verified")
        return
    from vllm_request_lifecycle_profiler.traceloom_adapter import (
        TraceLoomAdapterError,
        resolve_explicit_links,
    )

    try:
        resolved = resolve_explicit_links(database, links)
    except TraceLoomAdapterError:
        reasons.add("traceloom_resolution_failure")
        return
    if len(resolved) != len(links) or any(not row["resolved"] for row in resolved):
        reasons.add("unsupported_or_ambiguous_traceloom_link")
        return
    spans = {span["span_id"]: span for span in observation["lifecycle_spans"]}
    for row in resolved:
        if not row["source_lineage"]:
            reasons.add("traceloom_resolution_failure")
        span = spans[row["span_id"]]
        if "device" not in span["clock_domain"].lower():
            continue
        occurrence = row.get("tree_occurrence")
        if not isinstance(occurrence, Mapping):
            reasons.add("traceloom_device_occurrence_missing")
            continue
        if (
            occurrence.get("start_ns") != span["start_ns"]
            or occurrence.get("end_ns") != span["end_ns"]
        ):
            reasons.add("traceloom_device_occurrence_mismatch")
        total_us = occurrence.get("total_us")
        if (
            not _finite_number(total_us)
            or total_us < 0
            or span["accounted_duration_ms"] > total_us / 1000 + 1e-9
        ):
            reasons.add("traceloom_device_cost_mismatch")


def _validate_matching(value: Any, where: str) -> None:
    if not isinstance(value, Mapping):
        raise CaseValidationError(f"{where} must be an object")
    _exact_keys(value, _MATCHING_KEYS, where)
    for key in ("workload_id", "request_order_id"):
        if not _bounded_text(value[key], limit=128):
            raise CaseValidationError(f"{where}.{key} must be bounded")
    for key in ("prompt_tokens", "output_tokens", "concurrency"):
        item = value[key]
        if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
            raise CaseValidationError(f"{where}.{key} must be a positive integer")
    batch_shape = value["batch_shape"]
    if (
        not isinstance(batch_shape, list)
        or not batch_shape
        or len(batch_shape) > 16
        or any(
            isinstance(item, bool) or not isinstance(item, int) or item <= 0
            for item in batch_shape
        )
    ):
        raise CaseValidationError(
            f"{where}.batch_shape must contain 1-16 positive integers"
        )


def _validate_observation(
    value: Any, where: str, candidates: set[str], run_ids: set[str]
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CaseValidationError(f"{where} must be an object")
    _exact_keys(value, _OBSERVATION_KEYS, where)
    run_id = value.get("run_id")
    if not _bounded_text(run_id, limit=64) or run_id in run_ids:
        raise CaseValidationError(f"{where}.run_id must be bounded and unique")
    run_ids.add(run_id)
    if not _bounded_text(value.get("configuration_id"), limit=128):
        raise CaseValidationError(f"{where}.configuration_id must be bounded")
    if not _bounded_text(value.get("clock_model_id"), limit=128):
        raise CaseValidationError(f"{where}.clock_model_id must be bounded")
    metrics = value.get("metrics")
    if not isinstance(metrics, Mapping):
        raise CaseValidationError(f"{where}.metrics must be an object")
    _exact_keys(metrics, _METRIC_KEYS, f"{where}.metrics")
    for key, metric in metrics.items():
        if not _finite_number(metric) or metric < 0:
            raise CaseValidationError(f"{where}.metrics.{key} must be non-negative")
    if not isinstance(metrics["error_count"], int):
        raise CaseValidationError(f"{where}.metrics.error_count must be an integer")
    status = value.get("evidence_status")
    if not isinstance(status, Mapping):
        raise CaseValidationError(f"{where}.evidence_status must be an object")
    _exact_keys(status, _EVIDENCE_KEYS, f"{where}.evidence_status")
    if not isinstance(status["identity_complete"], bool):
        raise CaseValidationError(
            f"{where}.evidence_status.identity_complete must be boolean"
        )
    if not isinstance(status["clock_ambiguous"], bool):
        raise CaseValidationError(
            f"{where}.evidence_status.clock_ambiguous must be boolean"
        )
    if not isinstance(status["configuration_matched"], bool):
        raise CaseValidationError(
            f"{where}.evidence_status.configuration_matched must be boolean"
        )
    loss = status["event_loss_count"]
    if isinstance(loss, bool) or not isinstance(loss, int) or loss < 0:
        raise CaseValidationError(
            f"{where}.evidence_status.event_loss_count must be non-negative integer"
        )
    spans = value.get("lifecycle_spans")
    edges = value.get("lifecycle_edges")
    links = value.get("traceloom_links")
    normalized_events = value.get("normalized_events")
    if (
        not isinstance(normalized_events, list)
        or not isinstance(spans, list)
        or not isinstance(edges, list)
        or not isinstance(links, list)
    ):
        raise CaseValidationError(
            f"{where} events, spans, edges, and links must be lists"
        )
    if not normalized_events or not spans:
        raise CaseValidationError(
            f"{where} must contain normalized events and lifecycle spans"
        )
    for collection_name, collection in (
        ("normalized_events", normalized_events),
        ("lifecycle_spans", spans),
        ("lifecycle_edges", edges),
        ("traceloom_links", links),
    ):
        if len(collection) > DATA_CAPACITY_RECORDS:
            raise CaseValidationError(
                f"{where}.{collection_name} exceeds repository record capacity"
            )
    event_records: dict[str, Mapping[str, Any]] = {}
    for index, event in enumerate(normalized_events):
        event_where = f"{where}.normalized_events[{index}]"
        if not isinstance(event, Mapping):
            raise CaseValidationError(f"{event_where} must be an object")
        _exact_keys(
            event,
            _NORMALIZED_EVENT_KEYS,
            event_where,
            optional={"batch_id", "step_id"},
        )
        event_id = event["event_id"]
        if not _bounded_text(event_id, limit=96) or event_id in event_records:
            raise CaseValidationError(
                f"{event_where}.event_id must be bounded and unique"
            )
        event_records[event_id] = event
        for key in (
            "trace_id",
            "engine_lifecycle_id",
            "request_id",
            "clock_domain",
            "evidence_source",
            "support_state",
        ):
            if not _bounded_text(event[key], limit=128):
                raise CaseValidationError(f"{event_where}.{key} must be bounded")
        for key in ("batch_id", "step_id"):
            if key in event and not _bounded_text(event[key], limit=128):
                raise CaseValidationError(f"{event_where}.{key} must be bounded")
        if event["scope"] not in SCOPES:
            raise CaseValidationError(f"{event_where}.scope is not a runtime scope")
        if event["component"] not in COMPONENTS:
            raise CaseValidationError(
                f"{event_where}.component is not a runtime component"
            )
        if event["event_name"] not in EVENT_NAMES:
            raise CaseValidationError(
                f"{event_where}.event_name is not a runtime event"
            )
        if (
            EVENT_COMPONENT_BY_SCOPE.get((event["scope"], event["event_name"]))
            != event["component"]
        ):
            raise CaseValidationError(
                f"{event_where} has a component/event/scope ownership mismatch"
            )
        if (
            isinstance(event["recovery_epoch"], bool)
            or not isinstance(event["recovery_epoch"], int)
            or event["recovery_epoch"] < 0
        ):
            raise CaseValidationError(
                f"{event_where}.recovery_epoch must be non-negative integer"
            )
        if (
            isinstance(event["timestamp_ns"], bool)
            or not isinstance(event["timestamp_ns"], int)
            or event["timestamp_ns"] < 0
        ):
            raise CaseValidationError(
                f"{event_where}.timestamp_ns must be non-negative integer"
            )
    span_ids: set[str] = set()
    span_records: list[Mapping[str, Any]] = []
    span_by_id: dict[str, Mapping[str, Any]] = {}
    for index, span in enumerate(spans):
        span_where = f"{where}.lifecycle_spans[{index}]"
        if not isinstance(span, Mapping):
            raise CaseValidationError(f"{span_where} must be an object")
        _exact_keys(span, _SPAN_KEYS, span_where, optional={"batch_id", "step_id"})
        span_id = span["span_id"]
        if not _bounded_text(span_id, limit=96) or span_id in span_ids:
            raise CaseValidationError(
                f"{span_where}.span_id must be bounded and unique"
            )
        span_ids.add(span_id)
        span_records.append(span)
        span_by_id[span_id] = span
        start_event = event_records.get(span["start_event_id"])
        end_event = event_records.get(span["end_event_id"])
        if start_event is None or end_event is None:
            raise CaseValidationError(
                f"{span_where} references an unknown normalized event"
            )
        if (
            span["candidate_id"] not in candidates
            or span["candidate_id"] == "insufficient_evidence_or_multi_cause"
        ):
            raise CaseValidationError(
                f"{span_where}.candidate_id is not a measurable candidate"
            )
        for key in (
            "trace_id",
            "engine_lifecycle_id",
            "request_id",
            "owner",
            "clock_domain",
            "evidence_source",
            "support_state",
        ):
            if not _bounded_text(span[key], limit=128):
                raise CaseValidationError(f"{span_where}.{key} must be bounded")
        for key in ("batch_id", "step_id"):
            if key in span and not _bounded_text(span[key], limit=128):
                raise CaseValidationError(f"{span_where}.{key} must be bounded")
        if (
            isinstance(span["recovery_epoch"], bool)
            or not isinstance(span["recovery_epoch"], int)
            or span["recovery_epoch"] < 0
        ):
            raise CaseValidationError(
                f"{span_where}.recovery_epoch must be non-negative integer"
            )
        start, end = span["start_ns"], span["end_ns"]
        if (
            any(
                isinstance(item, bool) or not isinstance(item, int)
                for item in (start, end)
            )
            or end < start
        ):
            raise CaseValidationError(f"{span_where} has invalid interval")
        accounted = span["accounted_duration_ms"]
        duration = (end - start) / 1_000_000
        if (
            not _finite_number(accounted)
            or accounted < 0
            or accounted > duration + 1e-9
        ):
            raise CaseValidationError(
                f"{span_where}.accounted_duration_ms exceeds its interval"
            )
        identity_fields = (
            "trace_id",
            "engine_lifecycle_id",
            "recovery_epoch",
            "request_id",
            "clock_domain",
            "batch_id",
            "step_id",
        )
        if any(
            start_event.get(field) != span.get(field)
            or end_event.get(field) != span.get(field)
            for field in identity_fields
        ):
            raise CaseValidationError(
                f"{span_where} identity does not match its boundary events"
            )
        if start_event["timestamp_ns"] != start or end_event["timestamp_ns"] != end:
            raise CaseValidationError(
                f"{span_where} timestamps do not match its boundary events"
            )
    edge_identities: set[tuple[str, str, str]] = set()
    for index, edge in enumerate(edges):
        edge_where = f"{where}.lifecycle_edges[{index}]"
        if not isinstance(edge, Mapping):
            raise CaseValidationError(f"{edge_where} must be an object")
        _exact_keys(edge, _EDGE_KEYS, edge_where)
        if (
            edge["source_span_id"] not in span_ids
            or edge["target_span_id"] not in span_ids
        ):
            raise CaseValidationError(f"{edge_where} references an unknown span")
        if edge["kind"] not in _EDGE_KINDS:
            raise CaseValidationError(f"{edge_where}.kind is unsupported")
        edge_identity = (
            edge["source_span_id"],
            edge["target_span_id"],
            edge["kind"],
        )
        if edge_identity in edge_identities:
            raise CaseValidationError(f"{edge_where} duplicates an existing edge")
        edge_identities.add(edge_identity)
        source = span_by_id[edge["source_span_id"]]
        target = span_by_id[edge["target_span_id"]]
        request_identity = (
            "trace_id",
            "engine_lifecycle_id",
            "recovery_epoch",
            "request_id",
        )
        if any(source[key] != target[key] for key in request_identity):
            raise CaseValidationError(
                f"{edge_where} crosses request/lifecycle identity"
            )
        if edge["kind"] == "precedes" and source["end_ns"] > target["start_ns"]:
            raise CaseValidationError(f"{edge_where} violates temporal precedence")
    _validate_acyclic_edges(edges, span_ids, where)
    _validate_overlap_accounting(span_records, where)
    supported_link_span_ids: set[str] = set()
    link_identities: set[tuple[Any, ...]] = set()
    for index, link in enumerate(links):
        link_where = f"{where}.traceloom_links[{index}]"
        if not isinstance(link, Mapping):
            raise CaseValidationError(f"{link_where} must be an object")
        _exact_keys(
            link,
            _LINK_KEYS,
            link_where,
            optional={
                "batch_id",
                "step_id",
                "tree_id",
                "node_id",
                "occurrence_idx",
                "anchor_id",
                "event_id",
                "runtime_relation_id",
                "runtime_call_id",
                "device_work_id",
                "sync_action_id",
                "graph_event_id",
                "graph_envelope_id",
                "reason",
            },
        )
        if link["link_kind"] not in _LINK_KINDS:
            raise CaseValidationError(f"{link_where}.link_kind is unsupported")
        if link["evidence_source"] != "traceloom_sqlite":
            raise CaseValidationError(
                f"{link_where}.evidence_source must be traceloom_sqlite"
            )
        linked_span = span_by_id.get(link["span_id"])
        if linked_span is None:
            raise CaseValidationError(f"{link_where} references an unknown span")
        for key in (
            "trace_id",
            "engine_lifecycle_id",
            "request_id",
            "owner",
            "clock_domain",
            "evidence_source",
            "support_state",
        ):
            if not _bounded_text(link[key], limit=128):
                raise CaseValidationError(f"{link_where}.{key} must be bounded")
        if (
            isinstance(link["recovery_epoch"], bool)
            or not isinstance(link["recovery_epoch"], int)
            or link["recovery_epoch"] < 0
        ):
            raise CaseValidationError(
                f"{link_where}.recovery_epoch must be non-negative integer"
            )
        for key in (
            "batch_id",
            "step_id",
            "tree_id",
            "node_id",
            "anchor_id",
            "event_id",
            "runtime_relation_id",
            "runtime_call_id",
            "device_work_id",
            "sync_action_id",
            "graph_event_id",
            "graph_envelope_id",
            "reason",
        ):
            if key in link and not _bounded_text(link[key], limit=256):
                raise CaseValidationError(f"{link_where}.{key} must be bounded")
        if "occurrence_idx" in link and (
            isinstance(link["occurrence_idx"], bool)
            or not isinstance(link["occurrence_idx"], int)
            or link["occurrence_idx"] < 0
        ):
            raise CaseValidationError(
                f"{link_where}.occurrence_idx must be non-negative integer"
            )
        identity_fields = (
            "trace_id",
            "engine_lifecycle_id",
            "recovery_epoch",
            "request_id",
            "owner",
            "clock_domain",
            "batch_id",
            "step_id",
        )
        if any(link.get(field) != linked_span.get(field) for field in identity_fields):
            raise CaseValidationError(
                f"{link_where} identity does not match its lifecycle span"
            )
        link_identity = (
            link["span_id"],
            link["link_kind"],
            link.get("tree_id"),
            link.get("node_id"),
            link.get("occurrence_idx"),
            link.get("anchor_id"),
            link.get("event_id"),
            link.get("runtime_relation_id"),
            link.get("runtime_call_id"),
            link.get("device_work_id"),
            link.get("sync_action_id"),
            link.get("graph_event_id"),
            link.get("graph_envelope_id"),
        )
        if link_identity in link_identities:
            raise CaseValidationError(f"{link_where} duplicates an existing link")
        link_identities.add(link_identity)
        if link["support_state"] not in _SUPPORTED_STATES and not _bounded_text(
            link.get("reason"), limit=256
        ):
            raise CaseValidationError(
                f"{link_where}.reason is required for residual evidence"
            )
        if link["support_state"] in _SUPPORTED_STATES:
            trace_identity_keys = (
                "tree_id",
                "event_id",
                "runtime_relation_id",
                "runtime_call_id",
                "device_work_id",
                "sync_action_id",
                "graph_event_id",
                "graph_envelope_id",
            )
            if not any(link.get(key) is not None for key in trace_identity_keys):
                raise CaseValidationError(
                    f"{link_where} lacks an applicable TraceLoom identity"
                )
            if "device" in linked_span["clock_domain"].lower() and not all(
                link.get(key) is not None
                for key in ("tree_id", "node_id", "occurrence_idx", "anchor_id")
            ):
                raise CaseValidationError(
                    f"{link_where} lacks the required device drill-down chain"
                )
            if "device" in linked_span["clock_domain"].lower() and not all(
                linked_span.get(key) is not None for key in ("batch_id", "step_id")
            ):
                raise CaseValidationError(
                    f"{link_where} device evidence lacks batch/step identity"
                )
            supported_link_span_ids.add(link["span_id"])
    for span in span_records:
        if "device" not in span["clock_domain"].lower():
            continue
        if span["span_id"] not in supported_link_span_ids:
            raise CaseValidationError(
                f"{where} has a device-backed span without an explicit TraceLoom "
                "drill-down link"
            )
    return value


def _exact_keys(
    value: Mapping[str, Any],
    allowed: set[str],
    where: str,
    *,
    optional: set[str] | None = None,
) -> None:
    optional = optional or set()
    unknown = set(value) - allowed
    missing = allowed - optional - set(value)
    if unknown:
        raise CaseValidationError(f"{where} contains unknown keys: {sorted(unknown)}")
    if missing:
        raise CaseValidationError(f"{where} is missing keys: {sorted(missing)}")


def _reject_forbidden_keys(value: Any, path: str = "bundle") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).lower() in _FORBIDDEN_KEYS:
                raise CaseValidationError(
                    f"{path}.{key} is answer-bearing and forbidden"
                )
            _reject_forbidden_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden_keys(child, f"{path}[{index}]")


def _load_json(path: Path) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise CaseValidationError(f"non-finite JSON number is forbidden: {value}")

    payload = json.loads(
        path.read_text(encoding="utf-8"), parse_constant=reject_constant
    )
    if not isinstance(payload, dict):
        raise CaseValidationError("top-level JSON value must be an object")
    return payload


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _bounded_text(value: Any, *, limit: int = 128) -> bool:
    return isinstance(value, str) and 0 < len(value) <= limit and "\x00" not in value


def _candidate_totals(spans: Iterable[Mapping[str, Any]]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for span in spans:
        candidate = span["candidate_id"]
        totals[candidate] = totals.get(candidate, 0.0) + float(
            span["accounted_duration_ms"]
        )
    return totals


def _stage_totals(spans: Iterable[Mapping[str, Any]]) -> dict[str, float]:
    return {
        key: round(value, 9) for key, value in sorted(_candidate_totals(spans).items())
    }


def _validate_acyclic_edges(
    edges: Sequence[Mapping[str, Any]], span_ids: set[str], where: str
) -> None:
    successors: dict[str, list[str]] = {span_id: [] for span_id in span_ids}
    for edge in edges:
        successors[edge["source_span_id"]].append(edge["target_span_id"])
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(span_id: str) -> None:
        if span_id in visiting:
            raise CaseValidationError(f"{where}.lifecycle_edges contain a cycle")
        if span_id in visited:
            return
        visiting.add(span_id)
        for successor in successors[span_id]:
            visit(successor)
        visiting.remove(span_id)
        visited.add(span_id)

    for span_id in span_ids:
        visit(span_id)


def _validate_overlap_accounting(
    spans: Sequence[Mapping[str, Any]], where: str
) -> None:
    groups: dict[tuple[str, str, str, int, str], list[Mapping[str, Any]]] = {}
    for span in spans:
        key = (
            span["trace_id"],
            span["engine_lifecycle_id"],
            span["request_id"],
            span["recovery_epoch"],
            span["clock_domain"],
        )
        groups.setdefault(key, []).append(span)
    for group in groups.values():
        intervals = sorted((span["start_ns"], span["end_ns"]) for span in group)
        union_ns = 0
        if intervals:
            current_start, current_end = intervals[0]
            for start, end in intervals[1:]:
                if start <= current_end:
                    current_end = max(current_end, end)
                else:
                    union_ns += current_end - current_start
                    current_start, current_end = start, end
            union_ns += current_end - current_start
        accounted_ms = sum(float(span["accounted_duration_ms"]) for span in group)
        if accounted_ms > union_ns / 1_000_000 + 1e-9:
            raise CaseValidationError(
                f"{where}.lifecycle_spans double-charge overlapping evidence"
            )


def _iqr(values: Sequence[float]) -> float:
    ordered = sorted(values)
    return _nearest_rank(ordered, 0.75) - _nearest_rank(ordered, 0.25)


def _nearest_rank(ordered: Sequence[float], quantile: float) -> float:
    if not ordered:
        raise ValueError("cannot select a percentile from an empty sequence")
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]


def _percentile_interval(values: Sequence[float]) -> tuple[float, float]:
    ordered = sorted(values)
    return _nearest_rank(ordered, 0.025), _nearest_rank(ordered, 0.975)


def _bootstrap(
    pair_deltas: Mapping[str, Sequence[float]],
    candidates: Sequence[str],
    seed: int,
    resamples: int,
) -> dict[str, Any]:
    if resamples <= 0:
        raise ValueError("bootstrap_resamples must be positive")
    pair_count = len(next(iter(pair_deltas.values()))) if pair_deltas else 0
    if pair_count == 0:
        raise ValueError("at least one matched pair is required")
    rng = random.Random(seed)
    medians: dict[str, list[float]] = {candidate: [] for candidate in candidates}
    top1_counts = {candidate: 0 for candidate in candidates}
    for _ in range(resamples):
        indices = [rng.randrange(pair_count) for _ in range(pair_count)]
        sample_medians = {
            candidate: statistics.median(
                pair_deltas[candidate][index] for index in indices
            )
            for candidate in candidates
        }
        for candidate, value in sample_medians.items():
            medians[candidate].append(value)
        winner = min(candidates, key=lambda item: (-sample_medians[item], item))
        if sample_medians[winner] > 0:
            top1_counts[winner] += 1
    return {"medians": medians, "top1_counts": top1_counts}
