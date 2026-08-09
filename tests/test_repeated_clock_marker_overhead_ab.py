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


def _summary(pair_index: int = 0, order: str | None = None) -> dict:
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
    observed_order = order or ("A/B" if pair_index % 2 == 0 else "B/A")
    base_second = pair_index * 4
    disabled_second = base_second if observed_order == "A/B" else base_second + 1
    enabled_second = base_second + 1 if observed_order == "A/B" else base_second
    interval_base = 1_000_000 + pair_index * 100_000

    def variant(name: str, second: int, ordinal: int) -> dict:
        marker_enabled = name == "enabled"
        interval_offset = 0 if second == base_second else 20_000
        return {
            "client_run_metadata": {
                "model": "clock-ab-qwen",
                "observer_mode": "no-trace",
                "repo": {"commit": "a" * 40},
                "workload_source": {"commit": "b" * 40},
            },
            "profile_db_sha256": f"{ordinal:064x}",
            "provenance": {
                "artifact_label": "real-online v4.4 matched A/B",
                "case_id": "case",
                "client_command": [
                    "python",
                    "probe.py",
                    "--endpoint",
                    f"http://127.0.0.1:{18000 + ordinal}",
                    "--output-dir",
                    f"pair_{pair_index}/{name}",
                ],
                "clock_contract_version": "idle-evidence-contract-v4.4",
                "installed_runtime": {
                    "vllm_commit": "c" * 40,
                    "vllm_ascend_commit": "d" * 40,
                },
                "marker_enabled": marker_enabled,
                "mode": f"marker-{'enabled' if marker_enabled else 'disabled'}",
                "model": "/models/Qwen",
                "profiler_boundary": "matched-msprof-boundary",
                "profiler_options": {"task_time": "l0", "type": "db"},
                "request_shape": {"seed": 7, "max_tokens": 16},
                "server_command": [
                    "python",
                    "server.py",
                    "--port",
                    str(18000 + ordinal),
                    "--model",
                    "/models/Qwen",
                ],
                "timestamp_utc": f"2026-08-08T00:00:{second:02d}+00:00",
                "workload_commit": "b" * 40,
            },
            "sidecar": {
                "clock_model": {
                    "device_id": 6,
                    "target_clock_domain": "device",
                },
                "metadata": {
                    "attribution_rule_version": "host_device_projection_v2",
                    "contract_version": "idle-evidence-contract-v4.4",
                    "host_api_rules_sha256": "e" * 64,
                    "host_api_rules_version": "idle-evidence-host-api-v1",
                    "semantic_rules_sha256": "f" * 64,
                    "semantic_rules_version": "idle-evidence-semantic-v1",
                    "source_kind": "ascend_sqlite_hot_path",
                    "span_start_ns": interval_base + interval_offset,
                    "span_end_ns": interval_base + interval_offset + 10_000,
                },
            },
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
        "disabled": variant("disabled", disabled_second, pair_index * 2 + 1),
        "enabled": variant("enabled", enabled_second, pair_index * 2 + 2),
    }


def test_requires_three_accepted_pairs(tmp_path: Path) -> None:
    module = _module()
    for index in range(2):
        report = tmp_path / f"pair_{index:02d}" / "report"
        report.mkdir(parents=True)
        (report / "overhead_ab_summary.json").write_text(
            json.dumps(_summary(index))
        )
    with pytest.raises(ValueError, match="at least three"):
        module.aggregate(tmp_path)


def test_aggregates_repeated_pair_distribution(tmp_path: Path) -> None:
    module = _module()
    for index in range(3):
        summary = _summary(index)
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
    assert result["repetition_validation"]["capture_order"] == [
        "A/B",
        "B/A",
        "A/B",
    ]
    assert result["metrics"][0]["delta_percent_distribution"]["p50"] == 2.0
    assert result["correlated_e4"]["pooled_duration_ns"] == 150


def test_distribution_uses_cross_runtime_stable_summation() -> None:
    module = _module()
    values = [
        -0.011432623541677343,
        -0.31289387412839365,
        -0.16679157575391948,
    ]
    assert module._distribution(values)["mean"] == -0.16370602447466348


def _write_reports(tmp_path: Path, summaries: list[dict]) -> None:
    for index, summary in enumerate(summaries):
        report = tmp_path / f"pair_{index:02d}" / "report"
        report.mkdir(parents=True)
        (report / "overhead_ab_summary.json").write_text(json.dumps(summary))


def test_rejects_reused_capture_hash(tmp_path: Path) -> None:
    module = _module()
    summaries = [_summary(index) for index in range(3)]
    summaries[2]["disabled"]["profile_db_sha256"] = summaries[0]["disabled"][
        "profile_db_sha256"
    ]
    _write_reports(tmp_path, summaries)
    with pytest.raises(ValueError, match="reuses a source capture hash"):
        module.aggregate(tmp_path)


def test_rejects_non_alternating_capture_order(tmp_path: Path) -> None:
    module = _module()
    summaries = [_summary(0), _summary(1, order="A/B"), _summary(2)]
    _write_reports(tmp_path, summaries)
    with pytest.raises(ValueError, match="capture order is A/B, expected B/A"):
        module.aggregate(tmp_path)


def test_rejects_cross_pair_configuration_drift(tmp_path: Path) -> None:
    module = _module()
    summaries = [_summary(index) for index in range(3)]
    summaries[2]["enabled"]["provenance"]["model"] = "/models/Other"
    _write_reports(tmp_path, summaries)
    with pytest.raises(ValueError, match="frozen capture configuration differs"):
        module.aggregate(tmp_path)


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
