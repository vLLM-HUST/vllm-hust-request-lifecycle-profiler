#!/usr/bin/env python3
"""Aggregate at least three accepted matched marker-overhead A/B pairs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _distribution(values: list[float]) -> dict[str, float | int]:
    if not values:
        raise ValueError("cannot summarize an empty distribution")
    return {
        "count": len(values),
        "min": min(values),
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "max": max(values),
        # Python 3.12 changed built-in sum() to use compensated summation.
        # fsum() freezes report bytes across supported Python runtimes.
        "mean": math.fsum(values) / len(values),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()


def _normalized_command(command: list[str]) -> list[str]:
    result = list(command)
    for option, replacement in (
        ("--endpoint", "<variant-endpoint>"),
        ("--output-dir", "<variant-output>"),
        ("--port", "<variant-port>"),
    ):
        if option in result:
            result[result.index(option) + 1] = replacement
    return result


def _variant_frozen_configuration(
    report: dict[str, Any], variant: str
) -> dict[str, Any]:
    row = report[variant]
    provenance = row["provenance"]
    client_metadata = row["client_run_metadata"]
    sidecar_metadata = row["sidecar"]["metadata"]
    clock_model = row["sidecar"]["clock_model"]
    return {
        "artifact_label": provenance["artifact_label"],
        "case_id": provenance["case_id"],
        "client_command": _normalized_command(provenance["client_command"]),
        "client_model": client_metadata["model"],
        "clock_contract_version": provenance["clock_contract_version"],
        "device_id": clock_model["device_id"],
        "installed_runtime": provenance["installed_runtime"],
        "marker_enabled": provenance["marker_enabled"],
        "mode": provenance["mode"],
        "model": provenance["model"],
        "observer_mode": client_metadata["observer_mode"],
        "probe_commit": client_metadata["repo"]["commit"],
        "profiler_boundary": provenance["profiler_boundary"],
        "profiler_options": provenance["profiler_options"],
        "request_shape": provenance["request_shape"],
        "server_command": _normalized_command(provenance["server_command"]),
        "sidecar_attribution_rule_version": sidecar_metadata[
            "attribution_rule_version"
        ],
        "sidecar_contract_version": sidecar_metadata["contract_version"],
        "sidecar_host_api_rules_sha256": sidecar_metadata[
            "host_api_rules_sha256"
        ],
        "sidecar_host_api_rules_version": sidecar_metadata[
            "host_api_rules_version"
        ],
        "sidecar_semantic_rules_sha256": sidecar_metadata[
            "semantic_rules_sha256"
        ],
        "sidecar_semantic_rules_version": sidecar_metadata[
            "semantic_rules_version"
        ],
        "sidecar_source_kind": sidecar_metadata["source_kind"],
        "target_clock_domain": clock_model["target_clock_domain"],
        "workload_commit": provenance["workload_commit"],
        "workload_source_commit": client_metadata["workload_source"][
            "commit"
        ],
    }


def _pair_frozen_configuration(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "design": report["design"],
        "disabled": _variant_frozen_configuration(report, "disabled"),
        "enabled": _variant_frozen_configuration(report, "enabled"),
    }


def _capture_timestamp(report: dict[str, Any], variant: str) -> datetime:
    value = report[variant]["provenance"]["timestamp_utc"]
    timestamp = datetime.fromisoformat(value)
    if timestamp.tzinfo is None:
        raise ValueError(f"{variant}: capture timestamp lacks timezone")
    return timestamp


def _validate_repetitions(
    report_paths: list[Path], reports: list[dict[str, Any]]
) -> dict[str, Any]:
    capture_hashes: list[str] = []
    capture_timestamps: list[datetime] = []
    capture_intervals: list[tuple[int, int, str]] = []
    observed_order: list[str] = []
    frozen = _pair_frozen_configuration(reports[0])

    for index, (path, report) in enumerate(zip(report_paths, reports)):
        configuration = _pair_frozen_configuration(report)
        if configuration != frozen:
            raise ValueError(
                f"{path}: frozen capture configuration differs from pair_01"
            )
        disabled_time = _capture_timestamp(report, "disabled")
        enabled_time = _capture_timestamp(report, "enabled")
        order = "A/B" if disabled_time < enabled_time else "B/A"
        expected_order = "A/B" if index % 2 == 0 else "B/A"
        if order != expected_order:
            raise ValueError(
                f"{path}: capture order is {order}, expected {expected_order}"
            )
        observed_order.append(order)

        for variant, marker_enabled, mode in (
            ("disabled", False, "marker-disabled"),
            ("enabled", True, "marker-enabled"),
        ):
            row = report[variant]
            provenance = row["provenance"]
            if provenance["marker_enabled"] is not marker_enabled:
                raise ValueError(f"{path}: invalid {variant} marker mode")
            if provenance["mode"] != mode:
                raise ValueError(f"{path}: invalid {variant} provenance mode")
            source_hash = row.get("profile_db_sha256")
            if not isinstance(source_hash, str) or len(source_hash) != 64:
                raise ValueError(f"{path}: missing {variant} source hash")
            capture_hashes.append(source_hash)
            capture_timestamps.append(_capture_timestamp(report, variant))
            metadata = row["sidecar"]["metadata"]
            start_ns = int(metadata["span_start_ns"])
            end_ns = int(metadata["span_end_ns"])
            if end_ns <= start_ns:
                raise ValueError(f"{path}: invalid {variant} capture interval")
            capture_intervals.append((start_ns, end_ns, f"{path}:{variant}"))

    if len(set(capture_hashes)) != len(capture_hashes):
        raise ValueError("repeated matched A/B reuses a source capture hash")
    if len(set(capture_timestamps)) != len(capture_timestamps):
        raise ValueError("repeated matched A/B reuses a capture timestamp")
    for previous, current in zip(
        sorted(capture_intervals), sorted(capture_intervals)[1:]
    ):
        if current[0] < previous[1]:
            raise ValueError(
                "repeated matched A/B capture intervals overlap: "
                f"{previous[2]} and {current[2]}"
            )
    return {
        "capture_count": len(capture_hashes),
        "capture_order": observed_order,
        "distinct_source_hash_count": len(set(capture_hashes)),
        "frozen_configuration_sha256": _canonical_sha256(frozen),
        "non_overlapping_capture_intervals": True,
    }


def _artifact_manifest(root: Path) -> list[dict[str, Any]]:
    """Content-address the inputs needed to audit every accepted pair."""
    artifacts: list[dict[str, Any]] = []
    for pair_dir in sorted(root.glob("pair_*")):
        candidates: list[tuple[str, Path]] = []
        for variant in ("marker_disabled", "marker_enabled"):
            variant_dir = pair_dir / variant
            profile_databases = sorted(variant_dir.glob("profile/**/msprof_*.db"))
            if len(profile_databases) != 1:
                raise ValueError(
                    f"{variant_dir}: expected exactly one source msprof database"
                )
            candidates.append(("source_msprof_database", profile_databases[0]))
            run_dir = variant_dir / "run"
            for role, relative in (
                ("derived_sidecar", "traceloom_sidecar.db"),
                ("derived_analysis_result", "traceloom_result.json"),
                ("capture_provenance", "provenance.json"),
                ("client_probe_results", "client/probe_results.json"),
                ("client_run_metadata", "client/run_metadata.json"),
                ("client_summary", "client/summary.json"),
                ("iteration_timings", "iteration_timings.tsv"),
            ):
                candidates.append((role, run_dir / relative))
            marker_path = run_dir / "clock_marker_brackets.tsv"
            if marker_path.exists():
                candidates.append(("clock_marker_brackets", marker_path))
        for suffix in ("json", "md"):
            candidates.append((
                "pair_acceptance_report",
                pair_dir / "report" / f"overhead_ab_summary.{suffix}",
            ))
        for role, path in candidates:
            if not path.is_file():
                raise ValueError(f"missing audit artifact: {path}")
            artifacts.append({
                "pair_id": pair_dir.name,
                "role": role,
                "path": str(path.relative_to(root)),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            })
    return artifacts


def aggregate(root: Path) -> dict[str, Any]:
    report_paths = sorted(root.glob("pair_*/report/overhead_ab_summary.json"))
    if len(report_paths) < 3:
        raise ValueError("repeated matched A/B requires at least three pair reports")
    reports = [_load(path) for path in report_paths]
    required_acceptance = (
        "capture_acceptance",
        "protocol_acceptance",
        "calibration_acceptance",
        "full_idle_evidence_acceptance",
    )
    for path, report in zip(report_paths, reports):
        for field in required_acceptance:
            if report.get(field) != "PASS":
                raise ValueError(f"{path}: {field} is not PASS")
        failed_matches = [
            name for name, passed in report.get("matching_checks", {}).items()
            if passed is not True
        ]
        if failed_matches:
            raise ValueError(f"{path}: failed matching checks: {failed_matches}")

    repetition_validation = _validate_repetitions(report_paths, reports)
    design = reports[0]["design"]
    for path, report in zip(report_paths[1:], reports[1:]):
        if report["design"] != design:
            raise ValueError(f"{path}: experiment design differs from pair_01")
    metric_names = [row["metric"] for row in reports[0]["metrics"]]
    for path, report in zip(report_paths[1:], reports[1:]):
        if [row["metric"] for row in report["metrics"]] != metric_names:
            raise ValueError(f"{path}: metric set/order differs from pair_01")

    metric_summaries = []
    for metric_index, metric_name in enumerate(metric_names):
        rows = [report["metrics"][metric_index] for report in reports]
        disabled = [float(row["disabled"]) for row in rows]
        enabled = [float(row["enabled"]) for row in rows]
        deltas = [float(row["delta"]) for row in rows]
        delta_percent = [
            float(row["delta_percent"])
            for row in rows
            if row["delta_percent"] is not None
        ]
        pooled_disabled = math.fsum(disabled) / len(disabled)
        pooled_enabled = math.fsum(enabled) / len(enabled)
        pooled_delta = pooled_enabled - pooled_disabled
        metric_summaries.append({
            "metric": metric_name,
            "unit": rows[0]["unit"],
            "per_pair": [
                {"pair_id": report_paths[index].parents[1].name,
                 "disabled": rows[index]["disabled"],
                 "enabled": rows[index]["enabled"],
                 "delta": rows[index]["delta"],
                 "delta_percent": rows[index]["delta_percent"]}
                for index in range(len(rows))
            ],
            "delta_distribution": _distribution(deltas),
            "delta_percent_distribution": (
                _distribution(delta_percent) if delta_percent else None
            ),
            "pooled_pair_mean": {
                "disabled": pooled_disabled,
                "enabled": pooled_enabled,
                "delta": pooled_delta,
                "delta_percent": (
                    100.0 * pooled_delta / pooled_disabled
                    if pooled_disabled != 0.0 else None
                ),
            },
        })

    calibration_fields = (
        "epsilon_ns",
        "absolute_residual_p50_ns",
        "absolute_residual_p95_ns",
        "absolute_residual_max_ns",
        "host_clock_absolute_residual_p50_ns",
        "host_clock_absolute_residual_p95_ns",
        "host_clock_absolute_residual_max_ns",
        "composed_absolute_residual_p50_ns",
        "composed_absolute_residual_p95_ns",
        "composed_absolute_residual_max_ns",
        "drift_ppm",
    )
    calibration = {
        field: _distribution([
            float(report["enabled_calibration"][field]) for report in reports
        ])
        for field in calibration_fields
    }
    calibration["counts"] = {
        field: [int(report["enabled_calibration"][field]) for report in reports]
        for field in (
            "input_marker_count", "inlier_marker_count", "fit_marker_count",
            "validation_marker_count", "rejected_marker_count",
            "direct_overlap_marker_count", "ordinal_affine_fallback_marker_count",
        )
    }

    return {
        "schema_version": "clock-marker-repeated-overhead-ab-v1",
        "evidence_label": "real-online repeated matched A/B",
        "capture_acceptance": "PASS",
        "protocol_acceptance": "PASS",
        "calibration_acceptance": "PASS",
        "full_idle_evidence_acceptance": "PASS",
        "overhead_claim_status": "accepted_repeated_matched_ab",
        "raw_artifact_publication": {
            "status": "fresh_clone_raw_sources_and_regeneration_recipe",
            "bundle_manifest": (
                ".benchmarks/results/"
                "npu6_clock_marker_overhead_v44_l0_repeated_ab/"
                "fresh_clone_inputs/manifest.json"
            ),
            "analyzer_repository": "vLLM-HUST/vllm-hust-perf-analyzer",
            "analyzer_commit": (
                "9a816aaeda5d937c07d04e13901df1462d12f979"
            ),
            "external_archive_uri": None,
            "independent_raw_source_byte_retrieval": True,
            "derived_sidecar_regeneration": True,
            "original_derived_sidecar_byte_retrieval": False,
            "manifest_scope": (
                "six lossless raw msprof databases are committed as "
                "deterministic gzip archives; 45 direct inputs are committed; "
                "six derived sidecars are regenerated and semantically audited"
            ),
        },
        "pair_count": len(reports),
        "pair_ids": [path.parents[1].name for path in report_paths],
        "repetition_validation": repetition_validation,
        "design": design,
        "total_requests_per_variant": sum(
            int(report["design"]["request_count"]) for report in reports
        ),
        "matching_checks": {
            name: all(report["matching_checks"][name] for report in reports)
            for name in reports[0]["matching_checks"]
        },
        "metrics": metric_summaries,
        "calibration_per_capture_distribution": calibration,
        "correlated_e4": {
            "per_pair_count": [int(report["enabled_e4"]["count"]) for report in reports],
            "per_pair_duration_ns": [
                int(report["enabled_e4"]["duration_ns"]) for report in reports
            ],
            "pooled_count": sum(int(report["enabled_e4"]["count"]) for report in reports),
            "pooled_duration_ns": sum(
                int(report["enabled_e4"]["duration_ns"]) for report in reports
            ),
            "category": "queued_visible_task_delay",
            "evidence_level": "correlated",
            "evidence_relation": "exact_connection_id",
        },
        "pair_reports": [str(path.relative_to(root)) for path in report_paths],
    }


def _markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Repeated NPU6 clock-marker overhead A/B",
        "",
        f"- capture_acceptance: `{summary['capture_acceptance']}`",
        f"- protocol_acceptance: `{summary['protocol_acceptance']}`",
        f"- full_idle_evidence_acceptance: `{summary['full_idle_evidence_acceptance']}`",
        f"- overhead_claim_status: `{summary['overhead_claim_status']}`",
        f"- raw artifact publication: `{summary['raw_artifact_publication']['status']}`",
        f"- fresh-clone bundle: `{summary['raw_artifact_publication']['bundle_manifest']}`",
        f"- analyzer commit: `{summary['raw_artifact_publication']['analyzer_commit']}`",
        "- lossless raw msprof retrieval: `true`",
        "- derived sidecar regeneration and semantic audit: `true`",
        "- byte-identical original derived-sidecar retrieval: `false`",
        f"- pair_count: `{summary['pair_count']}`",
        (
            "- capture order: `"
            + ", ".join(summary["repetition_validation"]["capture_order"])
            + "`"
        ),
        (
            "- distinct raw captures: `"
            f"{summary['repetition_validation']['distinct_source_hash_count']}`"
        ),
        (
            "- frozen configuration SHA-256: `"
            f"{summary['repetition_validation']['frozen_configuration_sha256']}`"
        ),
        f"- total requests per variant: `{summary['total_requests_per_variant']}`",
        f"- pooled correlated E4: `{summary['correlated_e4']['pooled_count']}` slices / `{summary['correlated_e4']['pooled_duration_ns']}` ns",
        "",
        "| Metric | Disabled pair-mean | Enabled pair-mean | Delta | Delta % | per-pair Δ% p50 | per-pair Δ% p95 | Unit |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for metric in summary["metrics"]:
        pooled = metric["pooled_pair_mean"]
        distribution = metric["delta_percent_distribution"]
        delta_percent = "n/a" if pooled["delta_percent"] is None else f"{pooled['delta_percent']:.6f}"
        p50 = "n/a" if distribution is None else f"{distribution['p50']:.6f}"
        p95 = "n/a" if distribution is None else f"{distribution['p95']:.6f}"
        lines.append(
            f"| {metric['metric']} | {pooled['disabled']:.6f} | "
            f"{pooled['enabled']:.6f} | {pooled['delta']:.6f} | "
            f"{delta_percent} | {p50} | {p95} | {metric['unit']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    summary = aggregate(args.root)
    summary["artifact_manifest"] = _artifact_manifest(args.root)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "repeated_overhead_ab_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.output_dir / "repeated_overhead_ab_summary.md").write_text(
        _markdown(summary), encoding="utf-8"
    )
    print(json.dumps({
        "capture_acceptance": summary["capture_acceptance"],
        "overhead_claim_status": summary["overhead_claim_status"],
        "pair_count": summary["pair_count"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
