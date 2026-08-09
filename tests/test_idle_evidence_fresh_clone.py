from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path


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
    bundle, aggregate = _module().verify_static_bundle()

    assert bundle["schema_version"] == "idle-evidence-fresh-clone-bundle-v1"
    assert bundle["artifact_coverage"]["uncovered_artifact_count"] == 0
    assert len(bundle["archived_raw_sources"]) == 6
    assert len(bundle["regenerated_artifacts"]) == 6
    assert aggregate["full_idle_evidence_acceptance"] == "PASS"


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
