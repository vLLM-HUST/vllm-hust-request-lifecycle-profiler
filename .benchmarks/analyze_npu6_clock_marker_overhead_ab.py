#!/usr/bin/env python3
"""Build a structured fixed-rate marker overhead A/B report."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare matched marker-disabled and marker-enabled captures."
    )
    parser.add_argument("--disabled-dir", type=Path, required=True)
    parser.add_argument("--enabled-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--audit-sql", type=Path, default=DEFAULT_AUDIT_SQL)
    parser.add_argument(
        "--excluded-diagnostic",
        type=Path,
        action="append",
        default=[],
        help="Completed client run excluded from the official pair.",
    )
    return parser.parse_args()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _percentile(values: list[float], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * probability
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _distribution(values: list[float]) -> dict[str, float | int]:
    return {
        "count": len(values),
        "max": max(values) if values else 0.0,
        "min": min(values) if values else 0.0,
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "p99": _percentile(values, 0.99),
    }


def _iteration_summary(path: Path) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    with path.open(encoding="utf-8", newline="") as handle:
        rows.extend(csv.DictReader(handle, delimiter="\t"))
    durations_ms = [float(row["duration_ns"]) / 1_000_000.0 for row in rows]
    decode_rows = [
        row for row in rows if 1 <= int(row["scheduled_token_count"]) <= 4
    ]
    decode_durations_ms = [
        float(row["duration_ns"]) / 1_000_000.0 for row in decode_rows
    ]
    by_scheduled_token_count = {
        str(token_count): _distribution(
            [
                float(row["duration_ns"]) / 1_000_000.0
                for row in decode_rows
                if int(row["scheduled_token_count"]) == token_count
            ]
        )
        for token_count in range(1, 5)
    }
    marker_states: dict[str, int] = {}
    for row in rows:
        state = row["marker_state"]
        marker_states[state] = marker_states.get(state, 0) + 1
    return {
        "all_duration_ms": _distribution(durations_ms),
        "by_scheduled_token_count": by_scheduled_token_count,
        "decode_duration_ms": _distribution(decode_durations_ms),
        "decode_iteration_count": len(decode_rows),
        "iteration_count": len(rows),
        "marker_states": marker_states,
        "scheduled_token_count": sum(
            int(row["scheduled_token_count"]) for row in rows
        ),
    }


def _request_identity(path: Path) -> dict[str, Any]:
    probe = _load_json(path)
    records = [
        {
            "case_index": row["case_index"],
            "repeat": row["repeat"],
            "request_id": row["request_id"],
            "scheduled_offset_s": row["scheduled_offset_s"],
        }
        for row in probe["records"]
    ]
    payload = json.dumps(records, separators=(",", ":"), sort_keys=True).encode()
    return {
        "record_count": len(records),
        "schedule_sha256": hashlib.sha256(payload).hexdigest(),
    }


def _rows_by_key(
    connection: sqlite3.Connection, query: str, key: str
) -> dict[str, dict[str, Any]]:
    return {str(row[key]): dict(row) for row in connection.execute(query)}


def _sidecar_summary(path: Path, audit_sql: str) -> dict[str, Any]:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        model_rows = connection.execute(
            "select * from traceloom_clock_model order by device_id"
        ).fetchall()
        if len(model_rows) != 1:
            raise ValueError(f"{path}: expected exactly one clock model")
        metadata = dict(
            connection.execute("select * from traceloom_run_metadata").fetchone()
        )
        intervals = _rows_by_key(
            connection,
            "select interval_kind, count(*) as count, "
            "sum(duration_ns) as duration_ns from traceloom_device_interval "
            "group by interval_kind",
            "interval_kind",
        )
        evidence_levels = _rows_by_key(
            connection,
            "select evidence_level, count(*) as count, "
            "sum(duration_ns) as duration_ns from traceloom_idle_explanation "
            "group by evidence_level",
            "evidence_level",
        )
        categories = {
            f"{row['category']}:{row['evidence_level']}:{row['evidence_relation']}":
            dict(row)
            for row in connection.execute(
                "select category, evidence_level, evidence_relation, "
                "count(*) as count, sum(duration_ns) as duration_ns "
                "from traceloom_idle_explanation "
                "group by category, evidence_level, evidence_relation"
            )
        }
        marker_states = {
            str(row["marker_state"]): int(row["count"])
            for row in connection.execute(
                "select marker_state, count(*) as count "
                "from traceloom_clock_marker group by marker_state"
            )
        }
        audit_cursor = connection.execute(audit_sql)
        audit_row = audit_cursor.fetchone()
        if audit_row is None:
            raise ValueError(f"{path}: audit query returned no row")
        audit = dict(audit_row)
    finally:
        connection.close()
    productive_ns = int(intervals["productive_active"]["duration_ns"])
    visible_idle_ns = int(intervals["visible_productive_idle"]["duration_ns"])
    span_ns = productive_ns + visible_idle_ns
    return {
        "audit": audit,
        "categories": categories,
        "clock_model": dict(model_rows[0]),
        "device_intervals": intervals,
        "device_productive_fraction": productive_ns / span_ns,
        "evidence_levels": evidence_levels,
        "marker_states": marker_states,
        "metadata": metadata,
        "sidecar_path": str(path.resolve()),
    }


def _task_duration_diagnostics(path: Path) -> dict[str, Any]:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "select coalesce(s.value, '(unknown)') as task_type, "
            "count(*) as count from TASK t left join STRING_IDS s "
            "on s.id = t.taskType where t.endNs <= t.startNs "
            "group by coalesce(s.value, '(unknown)') order by count(*) desc"
        ).fetchall()
    finally:
        connection.close()
    point_task_types = {"EVENT_RECORD", "EVENT_WAIT", "PROFILING_ENABLE"}
    by_task_type = {str(row["task_type"]): int(row["count"]) for row in rows}
    return {
        "non_point_invalid_duration_count": sum(
            count
            for task_type, count in by_task_type.items()
            if task_type not in point_task_types
        ),
        "point_event_count": sum(
            count
            for task_type, count in by_task_type.items()
            if task_type in point_task_types
        ),
        "task_type_counts": by_task_type,
        "total_non_positive_duration_count": sum(by_task_type.values()),
    }


def _variant(path: Path, audit_sql: str) -> dict[str, Any]:
    run_dir = path / "run"
    client_dir = run_dir / "client"
    profile_dbs = sorted((path / "profile").glob("PROF_*/msprof_*.db"))
    if len(profile_dbs) != 1:
        raise ValueError(f"{path}: expected exactly one exported msprof DB")
    marker_path = run_dir / "clock_marker_brackets.tsv"
    marker_count = 0
    if marker_path.is_file():
        with marker_path.open(encoding="utf-8") as handle:
            marker_count = max(0, sum(1 for _ in handle) - 1)
    return {
        "client": _load_json(client_dir / "summary.json"),
        "iteration": _iteration_summary(run_dir / "iteration_timings.tsv"),
        "marker_bracket_count": marker_count,
        "profile_db": str(profile_dbs[0].resolve()),
        "provenance": _load_json(run_dir / "provenance.json"),
        "request_identity": _request_identity(client_dir / "probe_results.json"),
        "sidecar": _sidecar_summary(run_dir / "traceloom_sidecar.db", audit_sql),
        "task_duration_diagnostics": _task_duration_diagnostics(profile_dbs[0]),
        "variant_dir": str(path.resolve()),
    }


def _same_client_command(lhs: list[str], rhs: list[str]) -> bool:
    def normalized(command: list[str]) -> list[str]:
        result = list(command)
        if "--output-dir" in result:
            result[result.index("--output-dir") + 1] = "<variant-output>"
        return result

    return normalized(lhs) == normalized(rhs)


def _metric(
    name: str,
    unit: str,
    disabled: float | int,
    enabled: float | int,
) -> dict[str, Any]:
    disabled_value = float(disabled)
    enabled_value = float(enabled)
    delta = enabled_value - disabled_value
    return {
        "delta": delta,
        "delta_percent": (
            delta / disabled_value * 100.0 if disabled_value != 0 else None
        ),
        "disabled": disabled_value,
        "enabled": enabled_value,
        "metric": name,
        "unit": unit,
    }


def _metrics(disabled: dict[str, Any], enabled: dict[str, Any]) -> list[dict[str, Any]]:
    disabled_client = disabled["client"]
    enabled_client = enabled["client"]
    disabled_iteration = disabled["iteration"]
    enabled_iteration = enabled["iteration"]
    disabled_sidecar = disabled["sidecar"]
    enabled_sidecar = enabled["sidecar"]
    return [
        _metric(
            "request throughput",
            "request/s",
            disabled_client["request_throughput_per_s"],
            enabled_client["request_throughput_per_s"],
        ),
        _metric(
            "output chunk throughput",
            "chunk/s",
            disabled_client["output_chunk_throughput_per_s"],
            enabled_client["output_chunk_throughput_per_s"],
        ),
        _metric(
            "TTFT p50",
            "ms",
            disabled_client["first_token_ms"]["p50"],
            enabled_client["first_token_ms"]["p50"],
        ),
        _metric(
            "TTFT p95",
            "ms",
            disabled_client["first_token_ms"]["p95"],
            enabled_client["first_token_ms"]["p95"],
        ),
        _metric(
            "request latency p50",
            "ms",
            disabled_client["latency_ms"]["p50"],
            enabled_client["latency_ms"]["p50"],
        ),
        _metric(
            "request latency p95",
            "ms",
            disabled_client["latency_ms"]["p95"],
            enabled_client["latency_ms"]["p95"],
        ),
        _metric(
            "ITL p50",
            "ms",
            disabled_client["inter_token_latency_ms"]["p50"],
            enabled_client["inter_token_latency_ms"]["p50"],
        ),
        _metric(
            "ITL p95",
            "ms",
            disabled_client["inter_token_latency_ms"]["p95"],
            enabled_client["inter_token_latency_ms"]["p95"],
        ),
        _metric(
            "TPOT p50",
            "ms",
            disabled_client["tpot_ms"]["p50"],
            enabled_client["tpot_ms"]["p50"],
        ),
        _metric(
            "TPOT p95",
            "ms",
            disabled_client["tpot_ms"]["p95"],
            enabled_client["tpot_ms"]["p95"],
        ),
        _metric(
            "decode iteration duration p50",
            "ms",
            disabled_iteration["decode_duration_ms"]["p50"],
            enabled_iteration["decode_duration_ms"]["p50"],
        ),
        _metric(
            "decode iteration duration p95",
            "ms",
            disabled_iteration["decode_duration_ms"]["p95"],
            enabled_iteration["decode_duration_ms"]["p95"],
        ),
        _metric(
            "device productive time (full profiler boundary)",
            "ns",
            disabled_sidecar["device_intervals"]["productive_active"][
                "duration_ns"
            ],
            enabled_sidecar["device_intervals"]["productive_active"][
                "duration_ns"
            ],
        ),
        _metric(
            "device productive fraction (full profiler boundary)",
            "ratio",
            disabled_sidecar["device_productive_fraction"],
            enabled_sidecar["device_productive_fraction"],
        ),
        _metric(
            "raw marker brackets",
            "count",
            disabled["marker_bracket_count"],
            enabled["marker_bracket_count"],
        ),
    ]


def _excluded_diagnostic(path: Path) -> dict[str, Any]:
    summary = _load_json(path / "run" / "client" / "summary.json")
    return {
        "classification": "excluded_queueing_outlier",
        "reason": (
            "The 2 req/s capture entered a non-reproduced batching/queueing "
            "phase; it is retained but excluded from marker overhead deltas."
        ),
        "summary": summary,
        "variant_dir": str(path.resolve()),
    }


def _markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# NPU6 Fixed-rate Clock-marker Overhead A/B",
        "",
        f"- capture_acceptance: `{summary['capture_acceptance']}`",
        f"- protocol_acceptance: `{summary['protocol_acceptance']}`",
        f"- calibration_acceptance: `{summary['calibration_acceptance']}`",
        (
            "- full_idle_evidence_acceptance: "
            f"`{summary['full_idle_evidence_acceptance']}`"
        ),
        f"- overhead_claim_status: `{summary['overhead_claim_status']}`",
        f"- offered load: `{summary['design']['offered_rate_rps']} req/s`",
        f"- fixed window: `{summary['design']['fixed_offered_window_s']} s`",
        f"- measured requests: `{summary['design']['request_count']}`",
        "",
        "## Matching checks",
        "",
        "| Check | Match |",
        "| --- | --- |",
    ]
    for name, value in summary["matching_checks"].items():
        lines.append(f"| {name} | `{'yes' if value else 'no'}` |")
    lines.extend(
        [
            "",
            "## Observed enabled - disabled deltas",
            "",
            "| Metric | Disabled | Enabled | Delta | Delta % | Unit |",
            "| --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for metric in summary["metrics"]:
        delta_percent = metric["delta_percent"]
        percent_text = "n/a" if delta_percent is None else f"{delta_percent:.3f}%"
        lines.append(
            f"| {metric['metric']} | {metric['disabled']:.6f} | "
            f"{metric['enabled']:.6f} | {metric['delta']:.6f} | "
            f"{percent_text} | {metric['unit']} |"
        )
    model = summary["enabled_calibration"]
    e4 = summary["enabled_e4"]
    duration_diagnostics = summary["enabled"]["task_duration_diagnostics"]
    lines.extend(
        [
            "",
            "## Enabled calibration and E4",
            "",
            (
                f"Calibration is `{model['alignment_status']}` with "
                f"{model['input_marker_count']}/{model['inlier_marker_count']}/"
                f"{model['rejected_marker_count']} input/inlier/rejected markers, "
                f"{model['fit_marker_count']}/{model['validation_marker_count']} "
                "fit/validation markers."
            ),
            (
                "Residual p50/p95/max: "
                f"{model['absolute_residual_p50_ns']:.3f}/"
                f"{model['absolute_residual_p95_ns']:.3f}/"
                f"{model['absolute_residual_max_ns']:.3f} ns; "
                f"bracket p95 {model['bracket_uncertainty_p95_ns']:.3f} ns; "
                f"epsilon {model['epsilon_ns']} ns; drift "
                f"{model['drift_ppm']:.6f} ppm."
            ),
            (
                f"E4 emitted {e4['count']} calibrated exact-connection slices "
                f"covering {e4['duration_ns']} ns of queued-visible-task delay; "
                "these remain diagnostic because the run-level analysis status "
                "is invalid_input ("
                f"{duration_diagnostics['non_point_invalid_duration_count']} "
                "non-point and "
                f"{duration_diagnostics['point_event_count']} point-event "
                "non-positive-duration TASK rows)."
            ),
            "",
            "## Interpretation boundary",
            "",
            (
                "This is a real-online, fixed-rate matched pair. It measures an "
                "observed ~1–2% latency/iteration perturbation for this workload; "
                "it does not establish a population confidence interval or a "
                "universal overhead bound. Full-boundary device time includes "
                "server warm-up and profiler-tail effects and is diagnostic while "
                "the sidecar run status is invalid_input."
            ),
            "",
        ]
    )
    if summary["excluded_diagnostics"]:
        lines.extend(
            [
                "## Excluded diagnostics",
                "",
                (
                    "The retained diagnostic capture(s) are excluded from official "
                    "deltas because their batching/queueing state was not reproduced."
                ),
                "",
            ]
        )
    return "\n".join(lines)


def main() -> int:
    args = _parse_args()
    audit_sql = args.audit_sql.read_text(encoding="utf-8")
    disabled = _variant(args.disabled_dir, audit_sql)
    enabled = _variant(args.enabled_dir, audit_sql)
    disabled_provenance = disabled["provenance"]
    enabled_provenance = enabled["provenance"]
    matching_checks = {
        "client_command_except_output": _same_client_command(
            disabled_provenance["client_command"],
            enabled_provenance["client_command"],
        ),
        "fixed_request_schedule": (
            disabled["request_identity"] == enabled["request_identity"]
        ),
        "installed_runtime": (
            disabled_provenance["installed_runtime"]
            == enabled_provenance["installed_runtime"]
        ),
        "model": disabled_provenance["model"] == enabled_provenance["model"],
        "profiler_boundary": (
            disabled_provenance["profiler_boundary"]
            == enabled_provenance["profiler_boundary"]
        ),
        "profiler_options": (
            disabled_provenance["profiler_options"]
            == enabled_provenance["profiler_options"]
        ),
        "request_shape": (
            disabled_provenance["request_shape"]
            == enabled_provenance["request_shape"]
        ),
        "server_command": (
            disabled_provenance["server_command"]
            == enabled_provenance["server_command"]
        ),
        "workload_commit": (
            disabled_provenance["workload_commit"]
            == enabled_provenance["workload_commit"]
        ),
    }
    enabled_model = enabled["sidecar"]["clock_model"]
    e4_key = "queued_visible_task_delay:correlated:exact_connection_id"
    enabled_e4 = enabled["sidecar"]["categories"].get(
        e4_key,
        {"count": 0, "duration_ns": 0},
    )
    protocol_valid = (
        all(matching_checks.values())
        and disabled["client"]["success_count"]
        == disabled["client"]["request_count"]
        and enabled["client"]["success_count"]
        == enabled["client"]["request_count"]
        and disabled["sidecar"]["audit"]["audit_status"] == "PASS"
        and enabled["sidecar"]["audit"]["audit_status"] == "PASS"
        and disabled["marker_bracket_count"] == 0
        and enabled["marker_bracket_count"] > 0
    )
    calibration_valid = (
        enabled_model["alignment_status"] == "calibrated"
        and enabled_model["validation_marker_count"] > 0
        and enabled["sidecar"]["audit"]["audit_status"] == "PASS"
    )
    full_run_valid = (
        protocol_valid
        and calibration_valid
        and disabled["sidecar"]["metadata"]["analysis_status"] == "ok"
        and enabled["sidecar"]["metadata"]["analysis_status"] == "ok"
    )
    summary = {
        "calibration_acceptance": "PASS" if calibration_valid else "FAIL",
        "capture_acceptance": (
            "PASS"
            if full_run_valid
            else "PARTIAL"
            if protocol_valid and calibration_valid
            else "FAIL"
        ),
        "design": {
            "fixed_offered_window_s": enabled["client"][
                "fixed_offered_window_s"
            ],
            "offered_rate_rps": enabled["client"]["offered_rate_rps"],
            "request_count": enabled["client"]["request_count"],
            "schedule_sha256": enabled["request_identity"]["schedule_sha256"],
        },
        "disabled": disabled,
        "enabled": enabled,
        "enabled_calibration": enabled_model,
        "enabled_e4": enabled_e4,
        "evidence_label": "real-online fixed-rate matched marker overhead",
        "excluded_diagnostics": [
            _excluded_diagnostic(path) for path in args.excluded_diagnostic
        ],
        "full_idle_evidence_acceptance": "PASS" if full_run_valid else "FAIL",
        "matching_checks": matching_checks,
        "metrics": _metrics(disabled, enabled),
        "overhead_claim_status": "observed_single_pair_no_confidence_interval",
        "protocol_acceptance": "PASS" if protocol_valid else "FAIL",
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "overhead_ab_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "overhead_ab_summary.md").write_text(
        _markdown(summary),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "capture_acceptance": summary["capture_acceptance"],
                "output_dir": str(args.output_dir.resolve()),
                "overhead_claim_status": summary["overhead_claim_status"],
            },
            sort_keys=True,
        )
    )
    return 0 if protocol_valid and calibration_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
