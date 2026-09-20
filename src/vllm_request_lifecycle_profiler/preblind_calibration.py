"""Validation and reduction for the public pre-blind noise calibration.

The calibration contains no fault, case oracle, or opaque input.  It reduces
five matched no-intervention service pairs to the frozen scorer noise floor.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from vllm_request_lifecycle_profiler.blind_attribution import (
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    MAX_RESIDUAL_SHARE,
    MIN_DOMINANCE_SHARE,
    calibrate_noise_floor,
)

CALIBRATION_SCHEMA = "request-lifecycle-preblind-null-calibration/v1"
ABSTENTION_CANDIDATE = "insufficient_evidence_or_multi_cause"
PAIR_KEYS = {
    "pair_id",
    "order",
    "workload_id",
    "configuration_id",
    "arm_a",
    "arm_b",
}
ARM_KEYS = {
    "run_id",
    "intervention",
    "evidence_valid",
    "request_count",
    "candidate_totals_ms",
    "error_count",
}

_SPAN_CANDIDATES = {
    ("render_started", "render_done"): "frontend_tokenization",
    ("tokenization_started", "tokenization_done"): "frontend_tokenization",
    ("queued", "scheduled"): "queue_or_admission",
    ("requeued", "admission_started"): "queue_or_admission",
    ("admission_started", "resumed"): "queue_or_admission",
    # The runtime pin exposes only a coarse prefill interval.  Keep it in the
    # residual bucket rather than relabelling it as a device or KV root cause.
    ("prefill_started", "prefill_done"): ABSTENTION_CANDIDATE,
    ("decode_started", "decode_done"): "decode_execution",
    ("communication_started", "communication_done"): (
        "communication_or_synchronization"
    ),
    ("serialization_started", "serialization_done"): "response_streaming",
    ("delivery_started", "delivery_done"): "response_streaming",
    ("cleanup_started", "cleanup_done"): "cleanup_or_resource_release",
}


class CalibrationValidationError(ValueError):
    """The public null-calibration input is incomplete or unmatched."""


def build_calibration_report(
    pairs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate five null pairs and compute the preregistered noise floor."""

    if len(pairs) != 5:
        raise CalibrationValidationError("calibration requires exactly five pairs")
    pair_ids: set[str] = set()
    run_ids: set[str] = set()
    matched_workload_id: str | None = None
    matched_configuration_id: str | None = None
    matched_request_count: int | None = None
    matched_candidates: set[str] | None = None
    deltas: list[float] = []
    pair_candidate_deltas: list[dict[str, Any]] = []
    expected_order = ("AB", "BA", "AB", "BA", "AB")
    for index, (pair, order) in enumerate(zip(pairs, expected_order, strict=True)):
        where = f"pairs[{index}]"
        _exact_keys(pair, PAIR_KEYS, where)
        pair_id = _bounded_text(pair["pair_id"], limit=64, where=f"{where}.pair_id")
        if pair_id in pair_ids:
            raise CalibrationValidationError(f"{where}.pair_id must be unique")
        pair_ids.add(pair_id)
        if pair["order"] != order:
            raise CalibrationValidationError("calibration order must alternate AB/BA")
        workload_id = _bounded_text(
            pair["workload_id"], limit=128, where=f"{where}.workload_id"
        )
        configuration_id = _bounded_text(
            pair["configuration_id"],
            limit=128,
            where=f"{where}.configuration_id",
        )
        if matched_workload_id is None:
            matched_workload_id = workload_id
            matched_configuration_id = configuration_id
        elif (
            workload_id != matched_workload_id
            or configuration_id != matched_configuration_id
        ):
            raise CalibrationValidationError(
                "all calibration pairs must use the same workload and configuration"
            )
        arm_a = _validate_arm(pair["arm_a"], f"{where}.arm_a", run_ids)
        arm_b = _validate_arm(pair["arm_b"], f"{where}.arm_b", run_ids)
        if not workload_id or not configuration_id:  # pragma: no cover - helper raises.
            raise AssertionError
        if arm_a["request_count"] != arm_b["request_count"]:
            raise CalibrationValidationError(f"{where} has unmatched request counts")
        if matched_request_count is None:
            matched_request_count = arm_a["request_count"]
        elif arm_a["request_count"] != matched_request_count:
            raise CalibrationValidationError(
                "all calibration pairs must use the same request count"
            )
        a_totals = arm_a["candidate_totals_ms"]
        b_totals = arm_b["candidate_totals_ms"]
        if set(a_totals) != set(b_totals):
            raise CalibrationValidationError(f"{where} has unmatched candidates")
        if matched_candidates is None:
            matched_candidates = set(a_totals)
        elif set(a_totals) != matched_candidates:
            raise CalibrationValidationError(
                "all calibration pairs must use the same candidate set"
            )
        candidate_deltas = {
            candidate: float(b_totals[candidate]) - float(a_totals[candidate])
            for candidate in sorted(a_totals)
        }
        # Match the scorer's aggregation domain: the abstention bucket reports
        # unresolved coarse evidence, but it is not a measurable root-cause
        # candidate and therefore cannot inflate the calibrated decision floor.
        total_positive = sum(
            max(0.0, value)
            for candidate, value in candidate_deltas.items()
            if candidate != ABSTENTION_CANDIDATE
        )
        deltas.append(total_positive)
        pair_candidate_deltas.append(
            {
                "pair_id": pair_id,
                "candidate_deltas_ms": candidate_deltas,
                "total_positive_matched_delta_ms": total_positive,
            }
        )

    floor = calibrate_noise_floor(deltas)
    return {
        "schema": CALIBRATION_SCHEMA,
        "evidence_class": "real-online",
        "purpose": "public pre-blind no-intervention service-jitter calibration",
        "opaque_case_accessed": False,
        "pair_count": 5,
        "pair_orders": list(expected_order),
        "pair_candidate_deltas": pair_candidate_deltas,
        "total_positive_matched_deltas_ms": deltas,
        **floor,
        "scorer_configuration": {
            "minimum_absolute_floor_ms": 5.0,
            "insufficient_evidence_floor_ms": floor["insufficient_evidence_floor_ms"],
            "single_root_dominance": MIN_DOMINANCE_SHARE,
            "maximum_unexplained_residual_share": MAX_RESIDUAL_SHARE,
            "bootstrap_seed": BOOTSTRAP_SEED,
            "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
        },
    }


def _validate_arm(value: object, where: str, run_ids: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CalibrationValidationError(f"{where} must be an object")
    _exact_keys(value, ARM_KEYS, where)
    run_id = _bounded_text(value["run_id"], limit=64, where=f"{where}.run_id")
    if run_id in run_ids:
        raise CalibrationValidationError(f"{where}.run_id must be unique")
    run_ids.add(run_id)
    if value["intervention"] != "none":
        raise CalibrationValidationError(f"{where} must be no-intervention")
    if value["evidence_valid"] is not True:
        raise CalibrationValidationError(f"{where} evidence must be valid")
    count = value["request_count"]
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise CalibrationValidationError(f"{where}.request_count must be positive")
    errors = value["error_count"]
    if isinstance(errors, bool) or not isinstance(errors, int) or errors != 0:
        raise CalibrationValidationError(f"{where}.error_count must be zero")
    totals = value["candidate_totals_ms"]
    if not isinstance(totals, Mapping) or not totals:
        raise CalibrationValidationError(
            f"{where}.candidate_totals_ms must be a nonempty object"
        )
    for candidate, duration in totals.items():
        _bounded_text(candidate, limit=128, where=f"{where}.candidate_totals_ms key")
        if (
            isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not math.isfinite(float(duration))
            or duration < 0
        ):
            raise CalibrationValidationError(
                f"{where}.candidate_totals_ms[{candidate!r}] must be finite "
                "and non-negative"
            )
    return value


def summarize_runtime_run(run_dir: Path) -> dict[str, Any]:
    """Reduce one local real-service run without publishing raw host data."""

    analysis = _read_json(run_dir / "analysis.json")
    clients = _read_json(run_dir / "client_results.json")
    manifest = _read_json(run_dir / "manifest.json")
    results = clients.get("results")
    if not isinstance(results, list) or not results:
        raise CalibrationValidationError("client results must be nonempty")
    error_count = sum(
        1
        for result in results
        if not isinstance(result, Mapping)
        or result.get("http_status") != 200
        or result.get("error") is not None
    )
    records = _read_jsonl(run_dir)
    starts = Counter(
        str(row["process_uuid"])
        for row in records
        if row.get("record_type") == "process_start"
    )
    summary_rows = [
        row for row in records if row.get("record_type") == "process_summary"
    ]
    summaries = Counter(str(row["process_uuid"]) for row in summary_rows)
    summary_valid = (
        bool(starts)
        and starts == summaries
        and all(count == 1 for count in starts.values())
        and all(
            row.get("close_outcome") == "drained"
            and row.get("dropped_data_count") == 0
            and row.get("dropped_control_count") == 0
            and row.get("writer_failure_count") == 0
            for row in summary_rows
        )
    )
    loss_count = sum(1 for row in records if "loss" in str(row.get("record_type", "")))
    candidate_totals = _candidate_totals(records)
    evidence_valid = bool(
        analysis.get("evidence_valid") is True
        and summary_valid
        and loss_count == 0
        and error_count == 0
        and candidate_totals
    )
    return {
        "run_id": _bounded_text(
            manifest.get("run_id"), limit=64, where="manifest.run_id"
        ),
        "intervention": "none",
        "evidence_valid": evidence_valid,
        "request_count": len(results),
        "candidate_totals_ms": candidate_totals,
        "error_count": error_count,
    }


def _candidate_totals(records: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    starts: dict[tuple[str, str], Mapping[str, Any]] = {}
    totals: dict[str, float] = {}
    for row in records:
        if row.get("record_type") != "event":
            continue
        process_uuid = str(row.get("process_uuid", ""))
        start_span_id = row.get("start_span_id")
        if isinstance(start_span_id, str):
            starts[(process_uuid, start_span_id)] = row
        end_span_id = row.get("end_span_id")
        if not isinstance(end_span_id, str):
            continue
        start = starts.get((process_uuid, end_span_id))
        if start is None:
            continue
        candidate = _SPAN_CANDIDATES.get(
            (str(start.get("event_name")), str(row.get("event_name")))
        )
        if candidate is None:
            continue
        start_ns = start.get("timestamp_ns")
        end_ns = row.get("timestamp_ns")
        if (
            isinstance(start_ns, bool)
            or not isinstance(start_ns, int)
            or isinstance(end_ns, bool)
            or not isinstance(end_ns, int)
            or end_ns < start_ns
        ):
            raise CalibrationValidationError("runtime span has invalid timestamps")
        totals[candidate] = totals.get(candidate, 0.0) + (end_ns - start_ns) / 1e6
    return {
        candidate: round(duration, 9) for candidate, duration in sorted(totals.items())
    }


def _read_json(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise CalibrationValidationError(f"cannot read {path.name}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise CalibrationValidationError(f"{path.name} must contain an object")
    return value


def _read_jsonl(run_dir: Path) -> list[Mapping[str, Any]]:
    paths = sorted(run_dir.glob("trace.rlp.*.jsonl"))
    if not paths:
        raise CalibrationValidationError("runtime trace shards are missing")
    records: list[Mapping[str, Any]] = []
    for path in paths:
        try:
            lines = path.read_text().splitlines()
            values = [json.loads(line) for line in lines]
        except (OSError, json.JSONDecodeError) as exc:
            raise CalibrationValidationError(f"cannot read {path.name}: {exc}") from exc
        if any(not isinstance(value, Mapping) for value in values):
            raise CalibrationValidationError(f"{path.name} contains a non-object")
        records.extend(values)
    return records


def _exact_keys(value: Mapping[str, Any], expected: set[str], where: str) -> None:
    actual = set(value)
    if actual != expected:
        raise CalibrationValidationError(
            f"{where} keys differ: missing={sorted(expected - actual)}, "
            f"unknown={sorted(actual - expected)}"
        )


def _bounded_text(value: object, *, limit: int, where: str) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise CalibrationValidationError(f"{where} must be bounded text")
    return value


__all__ = [
    "CALIBRATION_SCHEMA",
    "CalibrationValidationError",
    "build_calibration_report",
    "summarize_runtime_run",
]
