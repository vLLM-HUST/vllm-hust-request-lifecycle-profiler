from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest


def _module():
    path = (
        Path(__file__).parents[1]
        / ".benchmarks"
        / "verify_idle_evidence_fresh_clone.py"
    )
    spec = importlib.util.spec_from_file_location("fresh_clone_audit", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_checked_in_fresh_clone_bundle_is_complete_and_consistent() -> None:
    module = _module()
    bundle, aggregate = module.verify_static_bundle()
    calibration = module.verify_calibration_sources()

    assert bundle["schema_version"] == "idle-evidence-fresh-clone-bundle-v1"
    assert bundle["artifact_coverage"]["uncovered_artifact_count"] == 0
    assert len(bundle["archived_raw_sources"]) == 6
    assert len(bundle["regenerated_artifacts"]) == 6
    assert aggregate["full_idle_evidence_acceptance"] == "PASS"
    assert calibration["schema_version"] == 2
    assert len(calibration["captures"]) == 3


def test_calibration_inputs_are_independent_content_identities() -> None:
    module = _module()
    manifest = json.loads(module.CALIBRATION_MANIFEST.read_text(encoding="utf-8"))
    module._require_unique_calibration_inputs(manifest)

    duplicate = copy.deepcopy(manifest)
    duplicate["captures"][1]["artifacts"]["source_msprof_db"]["sha256"] = (
        duplicate["captures"][0]["artifacts"]["source_msprof_db"]["sha256"]
    )
    with pytest.raises(ValueError, match="reuse source_msprof_db"):
        module._require_unique_calibration_inputs(duplicate)


def test_result_surface_excludes_reproducible_derived_artifacts() -> None:
    _module()._assert_layered_result_surface()


def test_pair_report_comparison_ignores_only_path_identity_metadata() -> None:
    module = _module()
    report_path = (
        module.RESULT_ROOT
        / "pair_01"
        / "report"
        / "overhead_ab_summary.json"
    )
    expected = json.loads(report_path.read_text(encoding="utf-8"))
    relocated = copy.deepcopy(expected)
    relocated["disabled"]["profile_db"] = "/tmp/relocated/msprof.db"
    relocated["disabled"]["sidecar"]["metadata"]["run_id"] = "new-run"
    relocated["disabled"]["sidecar"]["metadata"]["source_path"] = (
        "/tmp/relocated/msprof.db"
    )
    assert module._normalize_pair_report(relocated) == (
        module._normalize_pair_report(expected)
    )

    stale = copy.deepcopy(relocated)
    stale["metrics"][0]["enabled"] += 1.0
    assert module._normalize_pair_report(stale) != (
        module._normalize_pair_report(expected)
    )


def test_semantic_drift_error_reports_first_field() -> None:
    module = _module()
    expected = {"clock_model": {"epsilon_ns": 42, "status": "calibrated"}}
    observed = copy.deepcopy(expected)
    observed["clock_model"]["epsilon_ns"] = 43

    with pytest.raises(
        ValueError,
        match=r"semantic drift: \$\.clock_model\.epsilon_ns: expected 42, observed 43",
    ):
        module._require_same_semantics("semantic drift", expected, observed)


def test_sub_nanosecond_float_diagnostics_are_portable() -> None:
    module = _module()
    expected = {
        "clock_model": {
            "absolute_residual_max_ns": 30_692.74048813325,
            "drift_ppm": "17.343265",
        },
        "pooled": {
            "composed_absolute_validation_residual_ns": {
                "p95": "26538.197786"
            }
        },
    }
    observed = copy.deepcopy(expected)
    observed["clock_model"]["absolute_residual_max_ns"] = 30_692.625
    observed["clock_model"]["drift_ppm"] = "17.3432645"
    observed["pooled"]["composed_absolute_validation_residual_ns"]["p95"] = (
        "26538.000000"
    )

    module._require_same_semantics("semantic drift", expected, observed)
    assert module._portable_projection(expected, observed) == expected


def test_portable_float_tolerance_does_not_hide_material_or_integer_drift() -> None:
    module = _module()

    with pytest.raises(ValueError, match="absolute_residual_max_ns"):
        module._require_same_semantics(
            "semantic drift",
            {"absolute_residual_max_ns": 30_692.75},
            {"absolute_residual_max_ns": 30_692.249},
        )
    with pytest.raises(ValueError, match="epsilon_ns"):
        module._require_same_semantics(
            "semantic drift", {"epsilon_ns": 42}, {"epsilon_ns": 43}
        )
    with pytest.raises(ValueError, match="unrelated_metric"):
        module._require_same_semantics(
            "semantic drift", {"unrelated_metric": 1.0}, {"unrelated_metric": 1.1}
        )


def test_tolerated_diagnostic_drift_preserves_markdown_semantics() -> None:
    module = _module()
    analyzer = module._load_pair_analyzer()
    report_path = (
        module.RESULT_ROOT
        / "pair_01"
        / "report"
        / "overhead_ab_summary.json"
    )
    markdown_path = report_path.with_suffix(".md")
    expected = json.loads(report_path.read_text(encoding="utf-8"))
    observed = copy.deepcopy(expected)
    observed["enabled_calibration"]["absolute_residual_max_ns"] -= 0.125

    assert analyzer._markdown(observed) != markdown_path.read_text(encoding="utf-8")
    projected = module._portable_projection(expected, observed)
    assert analyzer._markdown(projected) == markdown_path.read_text(encoding="utf-8")


def test_calibration_report_normalizes_only_verified_rebuild_identities() -> None:
    module = _module()
    expected = json.loads(module.CALIBRATION_SUMMARY.read_text(encoding="utf-8"))
    observed = copy.deepcopy(expected)
    for index, capture in enumerate(observed["captures"]):
        run_id = f"{index + 1:064x}"
        capture["run_id"] = run_id
        capture["clock_model_id"] = (
            f"{run_id}:clock_model:0:{capture['device_id']}"
        )

    assert module._normalize_calibration_report(observed) == (
        module._normalize_calibration_report(expected)
    )
    observed["unique_run_id_count"] -= 1
    assert module._normalize_calibration_report(observed) != (
        module._normalize_calibration_report(expected)
    )
