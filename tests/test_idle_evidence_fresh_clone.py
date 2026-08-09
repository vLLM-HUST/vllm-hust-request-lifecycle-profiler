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
