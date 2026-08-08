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
    "source_clock_domain",
    "intermediate_clock_domain",
    "target_clock_domain",
    "mapping_kind",
    "profiler_caller_observation_kind",
    "marker_device_observation_kind",
    "scale",
    "offset_ns",
    "intercept_ns",
    "reference_host_ns",
    "reference_device_ns",
    "drift_ppm",
    "has_profiler_host_mapping",
    "marker_to_device_scale",
    "reference_marker_host_ns",
    "marker_reference_device_ns",
    "marker_to_device_drift_ppm",
    "profiler_to_marker_scale",
    "reference_profiler_host_ns",
    "profiler_reference_marker_ns",
    "profiler_to_marker_drift_ppm",
    "input_marker_count",
    "inlier_marker_count",
    "rejected_marker_count",
    "fit_marker_count",
    "validation_marker_count",
    "absolute_residual_p50_ns",
    "absolute_residual_p95_ns",
    "absolute_residual_max_ns",
    "bracket_uncertainty_p95_ns",
    "host_clock_absolute_residual_p50_ns",
    "host_clock_absolute_residual_p95_ns",
    "host_clock_absolute_residual_max_ns",
    "host_clock_uncertainty_p95_ns",
    "profiler_to_caller_bracket_uncertainty_p95_ns",
    "composed_absolute_residual_p50_ns",
    "composed_absolute_residual_p95_ns",
    "composed_absolute_residual_max_ns",
    "direct_overlap_marker_count",
    "ordinal_affine_fallback_marker_count",
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
        (probability * Decimal(len(ordered))).to_integral_value(rounding=ROUND_CEILING)
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


def _require_distribution_matches(
    path: Path,
    label: str,
    values: list[Decimal],
    reported: dict[str, object],
) -> None:
    expected = {
        "max": max(values) if values else Decimal(0),
        "p50": _nearest_rank(values, Decimal("0.50")),
        "p95": _nearest_rank(values, Decimal("0.95")),
    }
    tolerance = Decimal("0.001")
    for statistic, expected_value in expected.items():
        if abs(_decimal(reported[statistic]) - expected_value) > tolerance:
            raise ValueError(f"{path}: {label} {statistic} does not match marker rows")


def _one_capture(
    path: Path, audit_sql: str
) -> tuple[dict[str, Any], dict[str, list[Decimal]]]:
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
        expected_mapping = {
            "source_clock_domain": "profiler_host",
            "intermediate_clock_domain": "caller_clock_realtime",
            "target_clock_domain": "device",
            "mapping_kind": "composed_affine",
            "profiler_caller_observation_kind": (
                "record_api_midpoint_to_record_bracket_midpoint"
            ),
            "marker_device_observation_kind": (
                "record_sync_bracket_midpoint_to_task_start"
            ),
        }
        for column, expected in expected_mapping.items():
            if model[column] != expected:
                raise ValueError(
                    f"{path}: expected {column}={expected}, got {model[column]}"
                )
        if model["has_profiler_host_mapping"] != 1:
            raise ValueError(f"{path}: profiler-host mapping is unavailable")
        offset = _decimal(model["offset_ns"])
        intercept = _decimal(model["intercept_ns"])
        reference_host = _decimal(model["reference_host_ns"])
        reference_device = _decimal(model["reference_device_ns"])
        scale = _decimal(model["scale"])
        tolerance = Decimal("0.001")
        if abs(offset - (reference_device - reference_host)) > tolerance:
            raise ValueError(f"{path}: offset_ns is not the reference delta")
        serialized_scale_tolerance = abs(reference_host) * Decimal("0.0000000000005")
        if abs(intercept - (reference_device - scale * reference_host)) > (
            serialized_scale_tolerance + tolerance
        ):
            raise ValueError(f"{path}: intercept_ns is inconsistent with references")
        marker_rows = connection.execute(
            "select host_before_ns, record_after_ns, record_midpoint_ns, "
            "host_after_ns, host_midpoint_ns, "
            "profiler_host_midpoint_ns, device_timestamp_ns, marker_state, "
            "resolution_method, resolution_residual_ns "
            "from traceloom_clock_marker "
            "where clock_model_id = ? order by host_midpoint_ns",
            (model["clock_model_id"],),
        ).fetchall()
        marker_reference_host = _decimal(model["reference_marker_host_ns"])
        marker_reference_device = _decimal(model["marker_reference_device_ns"])
        marker_to_device_scale = _decimal(model["marker_to_device_scale"])
        profiler_reference_host = _decimal(model["reference_profiler_host_ns"])
        profiler_reference_marker = _decimal(model["profiler_reference_marker_ns"])
        profiler_to_marker_scale = _decimal(model["profiler_to_marker_scale"])
        composite_reference_host = _decimal(model["reference_host_ns"])
        composite_reference_device = _decimal(model["reference_device_ns"])
        composite_scale = _decimal(model["scale"])
        marker_device_validation_residuals: list[Decimal] = []
        profiler_marker_validation_residuals: list[Decimal] = []
        composed_validation_residuals: list[Decimal] = []
        bracket_uncertainties: list[Decimal] = []
        record_bracket_uncertainties: list[Decimal] = []
        fallback_resolution_residuals: list[Decimal] = []
        resolution_method_counts: dict[str, int] = {}
        for marker in marker_rows:
            if marker["marker_state"] == "rejected_marker":
                continue
            method = marker["resolution_method"]
            resolution_method_counts[method] = (
                resolution_method_counts.get(method, 0) + 1
            )
            if (
                method == "ordinal_affine_fallback"
                and marker["resolution_residual_ns"] is not None
            ):
                fallback_resolution_residuals.append(
                    _decimal(marker["resolution_residual_ns"])
                )
            half_width = Decimal(
                marker["host_after_ns"] - marker["host_before_ns"]
            ) / Decimal(2)
            bracket_uncertainties.append(abs(marker_to_device_scale) * half_width)
            if marker["record_after_ns"] is None:
                raise ValueError(f"{path}: marker lacks v4.4 record-call bracket")
            record_half_width = Decimal(
                marker["record_after_ns"] - marker["host_before_ns"]
            ) / Decimal(2)
            record_bracket_uncertainties.append(
                abs(marker_to_device_scale) * record_half_width
            )
            if marker["marker_state"] == "validation_marker":
                profiler_host_midpoint = marker["profiler_host_midpoint_ns"]
                if profiler_host_midpoint is None:
                    raise ValueError(
                        f"{path}: validation marker lacks profiler-host timestamp"
                    )
                marker_host = Decimal(marker["host_midpoint_ns"])
                record_host = marker["record_midpoint_ns"]
                if record_host is None:
                    raise ValueError(f"{path}: validation marker lacks record midpoint")
                profiler_host = Decimal(profiler_host_midpoint)
                marker_to_device = marker_reference_device + marker_to_device_scale * (
                    marker_host - marker_reference_host
                )
                profiler_to_marker = (
                    profiler_reference_marker
                    + profiler_to_marker_scale
                    * (profiler_host - profiler_reference_host)
                )
                composed_to_device = composite_reference_device + composite_scale * (
                    profiler_host - composite_reference_host
                )
                device_timestamp = Decimal(marker["device_timestamp_ns"])
                marker_device_validation_residuals.append(
                    abs(device_timestamp - marker_to_device)
                )
                profiler_marker_validation_residuals.append(
                    abs(Decimal(record_host) - profiler_to_marker)
                )
                composed_validation_residuals.append(
                    abs(device_timestamp - composed_to_device)
                )

        _require_distribution_matches(
            path,
            "marker-device residual",
            marker_device_validation_residuals,
            {
                "max": model["absolute_residual_max_ns"],
                "p50": model["absolute_residual_p50_ns"],
                "p95": model["absolute_residual_p95_ns"],
            },
        )
        expected_record_bracket_p95 = _nearest_rank(
            record_bracket_uncertainties, Decimal("0.95")
        )
        if abs(
            _decimal(model["profiler_to_caller_bracket_uncertainty_p95_ns"])
            - expected_record_bracket_p95
        ) > Decimal("0.001"):
            raise ValueError(f"{path}: record-call bracket p95 disagrees")
        epsilon_components = {
            "marker_device_validation_p95": _decimal(model["absolute_residual_p95_ns"]),
            "marker_bracket_uncertainty_p95": _decimal(
                model["bracket_uncertainty_p95_ns"]
            ),
            "profiler_caller_validation_p95_device": _decimal(
                model["host_clock_uncertainty_p95_ns"]
            ),
            "record_bracket_uncertainty_p95_device": _decimal(
                model["profiler_to_caller_bracket_uncertainty_p95_ns"]
            ),
        }
        expected_epsilon = sum(epsilon_components.values(), Decimal(0))
        expected_epsilon_ceil = int(
            expected_epsilon.to_integral_value(rounding=ROUND_CEILING)
        )
        if model["epsilon_ns"] != expected_epsilon_ceil:
            raise ValueError(f"{path}: epsilon does not equal the v4.4 four-term sum")
        _require_distribution_matches(
            path,
            "profiler-marker residual",
            profiler_marker_validation_residuals,
            {
                "max": model["host_clock_absolute_residual_max_ns"],
                "p50": model["host_clock_absolute_residual_p50_ns"],
                "p95": model["host_clock_absolute_residual_p95_ns"],
            },
        )
        _require_distribution_matches(
            path,
            "composed profiler-device residual",
            composed_validation_residuals,
            {
                "max": model["composed_absolute_residual_max_ns"],
                "p50": model["composed_absolute_residual_p50_ns"],
                "p95": model["composed_absolute_residual_p95_ns"],
            },
        )
        if (
            resolution_method_counts.get("direct_overlap", 0)
            != model["direct_overlap_marker_count"]
            or resolution_method_counts.get("ordinal_affine_fallback", 0)
            != model["ordinal_affine_fallback_marker_count"]
        ):
            raise ValueError(f"{path}: resolution provenance counts disagree")

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
            "select analysis_status, collection_status, source_kind, source_path, "
            "contract_version, attribution_rule_version "
            "from traceloom_run_metadata where run_id = ?",
            (model["run_id"],),
        ).fetchone()
        if metadata["contract_version"] != "idle-evidence-contract-v4.4":
            raise ValueError(f"{path}: expected idle-evidence-contract-v4.4")
        if metadata["attribution_rule_version"] != "host_device_projection_v2":
            raise ValueError(f"{path}: expected host_device_projection_v2")
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
        "record_bracket_uncertainty_p95_ns": _decimal_text(
            _decimal(model["profiler_to_caller_bracket_uncertainty_p95_ns"])
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
        "mapping": {
            "kind": model["mapping_kind"],
            "profiler_caller_observation_kind": model[
                "profiler_caller_observation_kind"
            ],
            "marker_device_observation_kind": model["marker_device_observation_kind"],
            "source_clock_domain": model["source_clock_domain"],
            "intermediate_clock_domain": model["intermediate_clock_domain"],
            "target_clock_domain": model["target_clock_domain"],
        },
        "drift_ppm": _decimal_text(_decimal(model["drift_ppm"])),
        "component_drift_ppm": {
            "marker_device": _decimal_text(
                _decimal(model["marker_to_device_drift_ppm"])
            ),
            "profiler_marker": _decimal_text(
                _decimal(model["profiler_to_marker_drift_ppm"])
            ),
            "profiler_caller": _decimal_text(
                _decimal(model["profiler_to_marker_drift_ppm"])
            ),
        },
        "epsilon_ns": model["epsilon_ns"],
        "epsilon_components_ns": {
            key: _decimal_text(value) for key, value in epsilon_components.items()
        },
        "fit_marker_count": model["fit_marker_count"],
        "inlier_marker_count": model["inlier_marker_count"],
        "input_marker_count": model["input_marker_count"],
        "link_status_counts": link_status_counts,
        "marker_resolution": {
            "direct_overlap_count": model["direct_overlap_marker_count"],
            "ordinal_affine_fallback_count": model[
                "ordinal_affine_fallback_marker_count"
            ],
            "observed_method_counts": resolution_method_counts,
            "fallback_residual_ns": _distribution(fallback_resolution_residuals),
        },
        "rejected_marker_count": model["rejected_marker_count"],
        "marker_device_residual_ns": {
            "max": _decimal_text(_decimal(model["absolute_residual_max_ns"])),
            "p50": _decimal_text(_decimal(model["absolute_residual_p50_ns"])),
            "p95": _decimal_text(_decimal(model["absolute_residual_p95_ns"])),
        },
        # Backward-compatible alias for the original marker→device report.
        "residual_ns": {
            "max": _decimal_text(_decimal(model["absolute_residual_max_ns"])),
            "p50": _decimal_text(_decimal(model["absolute_residual_p50_ns"])),
            "p95": _decimal_text(_decimal(model["absolute_residual_p95_ns"])),
        },
        "profiler_marker_residual_ns": {
            "max": _decimal_text(
                _decimal(model["host_clock_absolute_residual_max_ns"])
            ),
            "p50": _decimal_text(
                _decimal(model["host_clock_absolute_residual_p50_ns"])
            ),
            "p95": _decimal_text(
                _decimal(model["host_clock_absolute_residual_p95_ns"])
            ),
        },
        "profiler_caller_residual_ns": {
            "max": _decimal_text(
                _decimal(model["host_clock_absolute_residual_max_ns"])
            ),
            "p50": _decimal_text(
                _decimal(model["host_clock_absolute_residual_p50_ns"])
            ),
            "p95": _decimal_text(
                _decimal(model["host_clock_absolute_residual_p95_ns"])
            ),
        },
        "composed_profiler_device_residual_ns": {
            "max": _decimal_text(_decimal(model["composed_absolute_residual_max_ns"])),
            "p50": _decimal_text(_decimal(model["composed_absolute_residual_p50_ns"])),
            "p95": _decimal_text(_decimal(model["composed_absolute_residual_p95_ns"])),
        },
        "host_clock_uncertainty_p95_ns": _decimal_text(
            _decimal(model["host_clock_uncertainty_p95_ns"])
        ),
        "run_id": model["run_id"],
        "contract_version": metadata["contract_version"],
        "attribution_rule_version": metadata["attribution_rule_version"],
        "scale": model["scale"],
        "sidecar_path": str(path.resolve()),
        "source_kind": metadata["source_kind"],
        "source_path": metadata["source_path"],
        "validation_marker_count": model["validation_marker_count"],
    }
    return capture, {
        "marker_device_validation_residuals": marker_device_validation_residuals,
        "profiler_marker_validation_residuals": profiler_marker_validation_residuals,
        "composed_validation_residuals": composed_validation_residuals,
        "bracket_uncertainties": bracket_uncertainties,
        "record_bracket_uncertainties": record_bracket_uncertainties,
        "fallback_resolution_residuals": fallback_resolution_residuals,
    }


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
            "| Capture | Status/audit | Drift ppm marker→device / profiler→caller | "
            "Markers input/inlier/rejected | Fit/validation | Direct/fallback | "
            "Marker→device residual p50/p95/max (ns) | "
            "Profiler→caller residual p50/p95/max (ns) | Outer bracket p95 (ns) | "
            "Record-call bracket p95 (device ns) | "
            "Composed profiler→device residual p50/p95/max (ns) | "
            "Host-clock uncertainty p95 (device ns) | Epsilon (ns) | Correlated (ns) |"
        ),
        (
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | "
            "---: | ---: | ---: | ---: | ---: |"
        ),
    ]
    for capture in summary["captures"]:
        marker_device = capture["marker_device_residual_ns"]
        profiler_marker = capture["profiler_caller_residual_ns"]
        composed = capture["composed_profiler_device_residual_ns"]
        resolution = capture["marker_resolution"]
        lines.append(
            f"| `{Path(capture['sidecar_path']).parent.name}` | "
            f"`{capture['alignment_status']}/{capture['audit_status']}` | "
            f"{capture['component_drift_ppm']['marker_device']} / "
            f"{capture['component_drift_ppm']['profiler_marker']} | "
            f"{capture['input_marker_count']}/{capture['inlier_marker_count']}/"
            f"{capture['rejected_marker_count']} | "
            f"{capture['fit_marker_count']}/{capture['validation_marker_count']} | "
            f"{resolution['direct_overlap_count']}/"
            f"{resolution['ordinal_affine_fallback_count']} | "
            f"{marker_device['p50']}/{marker_device['p95']}/"
            f"{marker_device['max']} | "
            f"{profiler_marker['p50']}/{profiler_marker['p95']}/"
            f"{profiler_marker['max']} | "
            f"{capture['bracket_uncertainty_p95_ns']} | "
            f"{capture['record_bracket_uncertainty_p95_ns']} | "
            f"{composed['p50']}/{composed['p95']}/{composed['max']} | "
            f"{capture['host_clock_uncertainty_p95_ns']} | "
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
                "| marker→device absolute validation residual | "
                f"{pooled['marker_device_absolute_validation_residual_ns']['count']} | "
                f"{pooled['marker_device_absolute_validation_residual_ns']['p50']} | "
                f"{pooled['marker_device_absolute_validation_residual_ns']['p95']} | "
                f"{pooled['marker_device_absolute_validation_residual_ns']['max']} |"
            ),
            (
                "| profiler→caller absolute validation residual | "
                f"{pooled['profiler_caller_absolute_validation_residual_ns']['count']} | "
                f"{pooled['profiler_caller_absolute_validation_residual_ns']['p50']} | "
                f"{pooled['profiler_caller_absolute_validation_residual_ns']['p95']} | "
                f"{pooled['profiler_caller_absolute_validation_residual_ns']['max']} |"
            ),
            (
                "| composed profiler→device absolute validation residual | "
                f"{pooled['composed_absolute_validation_residual_ns']['count']} | "
                f"{pooled['composed_absolute_validation_residual_ns']['p50']} | "
                f"{pooled['composed_absolute_validation_residual_ns']['p95']} | "
                f"{pooled['composed_absolute_validation_residual_ns']['max']} |"
            ),
            (
                "| scaled half-bracket uncertainty | "
                f"{pooled['scaled_half_bracket_uncertainty_ns']['count']} | "
                f"{pooled['scaled_half_bracket_uncertainty_ns']['p50']} | "
                f"{pooled['scaled_half_bracket_uncertainty_ns']['p95']} | "
                f"{pooled['scaled_half_bracket_uncertainty_ns']['max']} |"
            ),
            (
                "| scaled record-call half-bracket uncertainty | "
                f"{pooled['scaled_record_call_half_bracket_uncertainty_ns']['count']} | "
                f"{pooled['scaled_record_call_half_bracket_uncertainty_ns']['p50']} | "
                f"{pooled['scaled_record_call_half_bracket_uncertainty_ns']['p95']} | "
                f"{pooled['scaled_record_call_half_bracket_uncertainty_ns']['max']} |"
            ),
            "",
            (
                "The composed residual is a shared-observation diagnostic, not "
                "independent clock-correctness validation. This artifact validates "
                "the v4.4 calibration mechanism. A zero correlated "
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
    pooled_marker_device_residuals: list[Decimal] = []
    pooled_profiler_marker_residuals: list[Decimal] = []
    pooled_composed_residuals: list[Decimal] = []
    pooled_brackets: list[Decimal] = []
    pooled_record_brackets: list[Decimal] = []
    pooled_fallback_resolution_residuals: list[Decimal] = []
    audit_sql = args.audit_sql.read_text(encoding="utf-8")
    for sidecar in args.sidecar:
        capture, distributions = _one_capture(sidecar, audit_sql)
        captures.append(capture)
        pooled_marker_device_residuals.extend(
            distributions["marker_device_validation_residuals"]
        )
        pooled_profiler_marker_residuals.extend(
            distributions["profiler_marker_validation_residuals"]
        )
        pooled_composed_residuals.extend(distributions["composed_validation_residuals"])
        pooled_brackets.extend(distributions["bracket_uncertainties"])
        pooled_record_brackets.extend(distributions["record_bracket_uncertainties"])
        pooled_fallback_resolution_residuals.extend(
            distributions["fallback_resolution_residuals"]
        )
    unique_run_ids = {capture["run_id"] for capture in captures}
    acceptance_status = (
        "PASS"
        if len(captures) >= 3
        and len(unique_run_ids) == len(captures)
        and all(capture["alignment_status"] == "calibrated" for capture in captures)
        and all(capture["audit_status"] == "PASS" for capture in captures)
        and all(capture["mapping"]["kind"] == "composed_affine" for capture in captures)
        and all(
            capture["mapping"]["profiler_caller_observation_kind"]
            == "record_api_midpoint_to_record_bracket_midpoint"
            and capture["mapping"]["marker_device_observation_kind"]
            == "record_sync_bracket_midpoint_to_task_start"
            for capture in captures
        )
        and all(
            capture["contract_version"] == "idle-evidence-contract-v4.4"
            and capture["attribution_rule_version"] == "host_device_projection_v2"
            for capture in captures
        )
        else "FAIL"
    )
    summary = {
        "acceptance_status": acceptance_status,
        "capture_count": len(captures),
        "captures": captures,
        "evidence_label": "real-online v4.4 calibration-chain repeated capture",
        "pooled": {
            # Backward-compatible alias for the original marker→device metric.
            "absolute_validation_residual_ns": _distribution(
                pooled_marker_device_residuals
            ),
            "marker_device_absolute_validation_residual_ns": _distribution(
                pooled_marker_device_residuals
            ),
            "profiler_marker_absolute_validation_residual_ns": _distribution(
                pooled_profiler_marker_residuals
            ),
            "profiler_caller_absolute_validation_residual_ns": _distribution(
                pooled_profiler_marker_residuals
            ),
            "composed_absolute_validation_residual_ns": _distribution(
                pooled_composed_residuals
            ),
            "scaled_half_bracket_uncertainty_ns": _distribution(pooled_brackets),
            "scaled_record_call_half_bracket_uncertainty_ns": _distribution(
                pooled_record_brackets
            ),
            "ordinal_affine_fallback_resolution_residual_ns": _distribution(
                pooled_fallback_resolution_residuals
            ),
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
