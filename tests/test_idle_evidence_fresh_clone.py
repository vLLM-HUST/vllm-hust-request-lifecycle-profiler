from __future__ import annotations

import importlib.util
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
