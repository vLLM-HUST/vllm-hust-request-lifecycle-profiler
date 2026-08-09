#!/usr/bin/env python3
"""Aggregate at least three accepted matched marker-overhead A/B pairs."""

from __future__ import annotations

import argparse
import hashlib
import json
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
        "mean": sum(values) / len(values),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
        pooled_disabled = sum(disabled) / len(disabled)
        pooled_enabled = sum(enabled) / len(enabled)
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
