from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


def _module():
    path = Path(__file__).parents[1] / ".benchmarks" / "analyze_repeated_clock_marker_overhead_ab.py"
    spec = importlib.util.spec_from_file_location("repeated_ab", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _summary() -> dict:
    matches = {"source_clean": True, "token_ids": True}
    calibration = {
        "epsilon_ns": 10,
        "absolute_residual_p50_ns": 1,
        "absolute_residual_p95_ns": 2,
        "absolute_residual_max_ns": 3,
        "host_clock_absolute_residual_p50_ns": 1,
        "host_clock_absolute_residual_p95_ns": 2,
        "host_clock_absolute_residual_max_ns": 3,
        "composed_absolute_residual_p50_ns": 1,
        "composed_absolute_residual_p95_ns": 2,
        "composed_absolute_residual_max_ns": 3,
        "drift_ppm": 4,
        "input_marker_count": 11,
        "inlier_marker_count": 11,
        "fit_marker_count": 9,
        "validation_marker_count": 2,
        "rejected_marker_count": 0,
        "direct_overlap_marker_count": 0,
        "ordinal_affine_fallback_marker_count": 11,
    }
    return {
        "capture_acceptance": "PASS",
        "protocol_acceptance": "PASS",
        "calibration_acceptance": "PASS",
        "full_idle_evidence_acceptance": "PASS",
        "matching_checks": matches,
        "design": {"request_count": 4, "seed": 7},
        "metrics": [{"metric": "TTFT p95", "unit": "ms", "disabled": 100.0,
                     "enabled": 101.0, "delta": 1.0, "delta_percent": 1.0}],
        "enabled_calibration": calibration,
        "enabled_e4": {"count": 2, "duration_ns": 50},
    }


def test_requires_three_accepted_pairs(tmp_path: Path) -> None:
    module = _module()
    for index in range(2):
        report = tmp_path / f"pair_{index:02d}" / "report"
        report.mkdir(parents=True)
        (report / "overhead_ab_summary.json").write_text(json.dumps(_summary()))
    with pytest.raises(ValueError, match="at least three"):
        module.aggregate(tmp_path)


def test_aggregates_repeated_pair_distribution(tmp_path: Path) -> None:
    module = _module()
    for index in range(3):
        summary = _summary()
        summary["metrics"][0]["enabled"] += index
        summary["metrics"][0]["delta"] += index
        summary["metrics"][0]["delta_percent"] += index
        report = tmp_path / f"pair_{index:02d}" / "report"
        report.mkdir(parents=True)
        (report / "overhead_ab_summary.json").write_text(json.dumps(summary))
    result = module.aggregate(tmp_path)
    assert result["capture_acceptance"] == "PASS"
    assert result["overhead_claim_status"] == "accepted_repeated_matched_ab"
    assert result["raw_artifact_publication"] == {
        "status": "fresh_clone_raw_sources_and_regeneration_recipe",
        "bundle_manifest": (
            ".benchmarks/results/"
            "npu6_clock_marker_overhead_v44_l0_repeated_ab/"
            "fresh_clone_inputs/manifest.json"
        ),
        "analyzer_repository": "vLLM-HUST/vllm-hust-perf-analyzer",
        "analyzer_commit": "9a816aaeda5d937c07d04e13901df1462d12f979",
        "external_archive_uri": None,
        "independent_raw_source_byte_retrieval": True,
        "derived_sidecar_regeneration": True,
        "original_derived_sidecar_byte_retrieval": False,
        "manifest_scope": (
            "six lossless raw msprof databases are committed as "
            "deterministic gzip archives; 45 direct inputs are committed; "
            "six derived sidecars are regenerated and semantically audited"
        ),
    }
    assert result["pair_count"] == 3
    assert result["metrics"][0]["delta_percent_distribution"]["p50"] == 2.0
    assert result["correlated_e4"]["pooled_duration_ns"] == 150


def test_artifact_manifest_hashes_audit_inputs(tmp_path: Path) -> None:
    module = _module()
    for pair_index in range(3):
        pair = tmp_path / f"pair_{pair_index:02d}"
        for variant in ("marker_disabled", "marker_enabled"):
            profile = pair / variant / "profile" / "PROF_1"
            profile.mkdir(parents=True)
            (profile / "msprof_test.db").write_bytes(b"profile")
            run = pair / variant / "run"
            (run / "client").mkdir(parents=True)
            for relative in (
                "traceloom_sidecar.db", "traceloom_result.json",
                "provenance.json",
                "client/probe_results.json", "client/run_metadata.json",
                "client/summary.json", "iteration_timings.tsv",
            ):
                (run / relative).write_text(relative, encoding="utf-8")
            if variant == "marker_enabled":
                (run / "clock_marker_brackets.tsv").write_text(
                    "marker_id\n", encoding="utf-8"
                )
        report = pair / "report"
        report.mkdir(parents=True)
        for suffix in ("json", "md"):
            (report / f"overhead_ab_summary.{suffix}").write_text(
                suffix, encoding="utf-8"
            )

    manifest = module._artifact_manifest(tmp_path)
    assert len(manifest) == 57
    assert all(len(row["sha256"]) == 64 for row in manifest)
    assert {row["role"] for row in manifest} >= {
        "source_msprof_database", "derived_sidecar", "clock_marker_brackets"
    }
