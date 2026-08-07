#!/usr/bin/env python3
"""Aggregate repeated real TraceLoom clock-calibration sidecars."""

from __future__ import annotations

import argparse
import json
import sqlite3
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIT_SQL = (
    REPO_ROOT.parent
    / "vllm-hust-perf-analyzer"
    / "docs"
    / "report-sql"
    / "idle-evidence-audit.sql"
)

MODEL_COLUMNS = (
    "clock_model_id",
    "run_id",
    "device_id",
    "scale",
    "offset_ns",
    "reference_host_ns",
    "reference_device_ns",
    "drift_ppm",
    "input_marker_count",
    "inlier_marker_count",
    "rejected_marker_count",
    "fit_marker_count",
    "validation_marker_count",
    "absolute_residual_p50_ns",
    "absolute_residual_p95_ns",
    "absolute_residual_max_ns",
    "bracket_uncertainty_p95_ns",
    "epsilon_ns",
    "alignment_status",
    "reason",
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Report per-capture and pooled host/device alignment quality."
    )
    parser.add_argument(
        "--sidecar",
        type=Path,
        action="append",
        required=True,
        help="Repeated TraceLoom sidecar; pass at least three times.",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--require-three", action="store_true")
    parser.add_argument("--audit-sql", type=Path, default=DEFAULT_AUDIT_SQL)
    return parser.parse_args()


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


def _decimal_text(value: Decimal, places: int = 6) -> str:
    quantum = Decimal(1).scaleb(-places)
    return format(value.quantize(quantum), "f")


def _nearest_rank(values: list[Decimal], probability: Decimal) -> Decimal:
    if not values:
        return Decimal(0)
    ordered = sorted(values)
    rank = int(
        (probability * Decimal(len(ordered))).to_integral_value(
            rounding=ROUND_CEILING
        )
    )
    rank = max(1, min(len(ordered), rank))
    return ordered[rank - 1]


def _distribution(values: list[Decimal]) -> dict[str, str | int]:
    return {
        "count": len(values),
        "max": _decimal_text(max(values) if values else Decimal(0)),
        "p50": _decimal_text(_nearest_rank(values, Decimal("0.50"))),
        "p95": _decimal_text(_nearest_rank(values, Decimal("0.95"))),
    }


def _one_capture(
    path: Path, audit_sql: str
) -> tuple[dict[str, Any], list[Decimal], list[Decimal]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        model_rows = connection.execute(
            f"select {', '.join(MODEL_COLUMNS)} from traceloom_clock_model "
            "order by device_id"
        ).fetchall()
        if len(model_rows) != 1:
            raise ValueError(f"{path}: expected exactly one clock model")
        model = dict(model_rows[0])
        if model["alignment_status"] != "calibrated":
            raise ValueError(
                f"{path}: expected calibrated, got {model['alignment_status']}"
            )
        marker_rows = connection.execute(
            "select host_before_ns, host_after_ns, host_midpoint_ns, "
            "device_timestamp_ns, marker_state from traceloom_clock_marker "
            "where clock_model_id = ? order by host_midpoint_ns",
            (model["clock_model_id"],),
        ).fetchall()
        reference_host = _decimal(model["reference_host_ns"])
        reference_device = _decimal(model["reference_device_ns"])
        scale = _decimal(model["scale"])
        validation_residuals: list[Decimal] = []
        bracket_uncertainties: list[Decimal] = []
        for marker in marker_rows:
            if marker["marker_state"] == "rejected_marker":
                continue
            half_width = Decimal(
                marker["host_after_ns"] - marker["host_before_ns"]
            ) / Decimal(2)
            bracket_uncertainties.append(abs(scale) * half_width)
            if marker["marker_state"] == "validation_marker":
                mapped = reference_device + scale * (
                    Decimal(marker["host_midpoint_ns"]) - reference_host
                )
                validation_residuals.append(
                    abs(Decimal(marker["device_timestamp_ns"]) - mapped)
                )

        explanations = {
            row["evidence_level"]: {
                "duration_ns": row["duration_ns"],
                "slice_count": row["slice_count"],
            }
            for row in connection.execute(
                "select evidence_level, count(*) as slice_count, "
                "sum(duration_ns) as duration_ns "
                "from traceloom_idle_explanation group by evidence_level"
            )
        }
        link_status_counts = {
            row["link_status"]: row["link_count"]
            for row in connection.execute(
                "select link_status, count(*) as link_count "
                "from traceloom_task_api_link group by link_status"
            )
        }
        metadata = connection.execute(
            "select analysis_status, collection_status, source_kind, source_path "
            "from traceloom_run_metadata where run_id = ?",
            (model["run_id"],),
        ).fetchone()
        audit_cursor = connection.execute(audit_sql)
        audit_row = audit_cursor.fetchone()
        if audit_row is None:
            raise ValueError(f"{path}: audit query returned no row")
        audit_status = audit_row["audit_status"]
    finally:
        connection.close()

    capture = {
        "alignment_status": model["alignment_status"],
        "analysis_status": metadata["analysis_status"],
        "audit_status": audit_status,
        "bracket_uncertainty_p95_ns": _decimal_text(
            _decimal(model["bracket_uncertainty_p95_ns"])
        ),
        "clock_model_id": model["clock_model_id"],
        "collection_status": metadata["collection_status"],
        "correlated_duration_ns": explanations.get("correlated", {}).get(
            "duration_ns", 0
        ),
        "correlated_slice_count": explanations.get("correlated", {}).get(
            "slice_count", 0
        ),
        "device_id": model["device_id"],
        "drift_ppm": _decimal_text(_decimal(model["drift_ppm"])),
        "epsilon_ns": model["epsilon_ns"],
        "fit_marker_count": model["fit_marker_count"],
        "inlier_marker_count": model["inlier_marker_count"],
        "input_marker_count": model["input_marker_count"],
        "link_status_counts": link_status_counts,
        "rejected_marker_count": model["rejected_marker_count"],
        "residual_ns": {
            "max": _decimal_text(_decimal(model["absolute_residual_max_ns"])),
            "p50": _decimal_text(_decimal(model["absolute_residual_p50_ns"])),
            "p95": _decimal_text(_decimal(model["absolute_residual_p95_ns"])),
        },
        "run_id": model["run_id"],
        "scale": model["scale"],
        "sidecar_path": str(path.resolve()),
        "source_kind": metadata["source_kind"],
        "source_path": metadata["source_path"],
        "validation_marker_count": model["validation_marker_count"],
    }
    return capture, validation_residuals, bracket_uncertainties


def _markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# NPU6 Host→Device Clock Calibration",
        "",
        f"- evidence_label: `{summary['evidence_label']}`",
        f"- capture_count: `{summary['capture_count']}`",
        f"- acceptance_status: `{summary['acceptance_status']}`",
        "",
        "## Per-capture models",
        "",
        (
            "| Capture | Status/audit | Drift ppm | Markers input/inlier/rejected | "
            "Fit/validation | Residual p50/p95/max (ns) | Bracket p95 (ns) | "
            "Epsilon (ns) | Correlated (ns) |"
        ),
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for capture in summary["captures"]:
        residual = capture["residual_ns"]
        lines.append(
            f"| `{Path(capture['sidecar_path']).parent.name}` | "
            f"`{capture['alignment_status']}/{capture['audit_status']}` | "
            f"{capture['drift_ppm']} | "
            f"{capture['input_marker_count']}/{capture['inlier_marker_count']}/"
            f"{capture['rejected_marker_count']} | "
            f"{capture['fit_marker_count']}/{capture['validation_marker_count']} | "
            f"{residual['p50']}/{residual['p95']}/{residual['max']} | "
            f"{capture['bracket_uncertainty_p95_ns']} | "
            f"{capture['epsilon_ns']} | {capture['correlated_duration_ns']} |"
        )
    pooled = summary["pooled"]
    lines.extend(
        [
            "",
            "## Pooled marker distributions",
            "",
            "| Metric | Count | p50 (ns) | p95 (ns) | max (ns) |",
            "| --- | ---: | ---: | ---: | ---: |",
            (
                "| absolute validation residual | "
                f"{pooled['absolute_validation_residual_ns']['count']} | "
                f"{pooled['absolute_validation_residual_ns']['p50']} | "
                f"{pooled['absolute_validation_residual_ns']['p95']} | "
                f"{pooled['absolute_validation_residual_ns']['max']} |"
            ),
            (
                "| scaled half-bracket uncertainty | "
                f"{pooled['scaled_half_bracket_uncertainty_ns']['count']} | "
                f"{pooled['scaled_half_bracket_uncertainty_ns']['p50']} | "
                f"{pooled['scaled_half_bracket_uncertainty_ns']['p95']} | "
                f"{pooled['scaled_half_bracket_uncertainty_ns']['max']} |"
            ),
            "",
            (
                "This artifact validates calibration quality. A zero correlated "
                "duration means no E4 gap passed the robust host-evidence gate; it "
                "is not converted into a positive attribution claim."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    args = _parse_args()
    if args.require_three and len(args.sidecar) < 3:
        raise ValueError("at least three repeated sidecars are required")
    captures: list[dict[str, Any]] = []
    pooled_residuals: list[Decimal] = []
    pooled_brackets: list[Decimal] = []
    audit_sql = args.audit_sql.read_text(encoding="utf-8")
    for sidecar in args.sidecar:
        capture, residuals, brackets = _one_capture(sidecar, audit_sql)
        captures.append(capture)
        pooled_residuals.extend(residuals)
        pooled_brackets.extend(brackets)
    unique_run_ids = {capture["run_id"] for capture in captures}
    acceptance_status = (
        "PASS"
        if len(captures) >= 3
        and len(unique_run_ids) == len(captures)
        and all(capture["alignment_status"] == "calibrated" for capture in captures)
        and all(capture["audit_status"] == "PASS" for capture in captures)
        else "FAIL"
    )
    summary = {
        "acceptance_status": acceptance_status,
        "capture_count": len(captures),
        "captures": captures,
        "evidence_label": "real-online calibration-chain repeated capture",
        "pooled": {
            "absolute_validation_residual_ns": _distribution(pooled_residuals),
            "scaled_half_bracket_uncertainty_ns": _distribution(pooled_brackets),
        },
        "unique_run_id_count": len(unique_run_ids),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "calibration_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.output_dir / "calibration_summary.md").write_text(
        _markdown(summary), encoding="utf-8"
    )
    print(json.dumps(summary, sort_keys=True))
    return 0 if acceptance_status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
