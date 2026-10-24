"""Methods retain protocol values; historical observations have fixed custody."""

import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "protocol_capsule", ROOT / "scripts/fetch_mod_consumer_evidence.py"
)
CAPSULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CAPSULE)
fetch = CAPSULE.fetch


def bindings():
    return json.loads((ROOT / "docs/protocol_evidence_bindings.json").read_text())


def test_protocol_parameters_and_scopes_preserved():
    g4 = (ROOT / "docs/g4_execution_spec.md").read_text()
    g6 = (ROOT / "docs/g6_counterfactual_spec.md").read_text()
    public = (ROOT / "docs/issue19_public_evidence.md").read_text()
    plan = (ROOT / "docs/experiment_plan.md").read_text()
    assert "8589934592" in g4 and "3 independent lifecycles" in g4
    assert "median(tail_s)_base > 10 s" in g6
    assert "median(tail_s)_head < 5 s" in g6
    assert "fixed" in public and "8/10" in public and "NO_GO" in public
    assert "NOT_M0_PROVEN" in plan and "## Required Artifact Fields" in plan
    assert "## Phase 0" in plan and "## Phase 2" in plan
    assert ".benchmarks/results/" not in plan
    assert "~40 s" not in g6 and "+1.1 s" not in g4
    assert "TTFT p95 is 12299.08" not in plan
    assert (
        "pinned historical implementation map"
        in (ROOT / "docs/kv_recovery_runtime_callsite_map.md").read_text()
    )


def test_binding_navigation_and_no_invented_recovery():
    mapping = bindings()
    navigation = (ROOT / "docs/protocol_evidence.md").read_text()
    assert mapping["bindings"]
    seen = set()
    for row in mapping["bindings"]:
        identity = (row["document"], row["legacy_path"])
        assert identity not in seen
        seen.add(identity)
        assert row["legacy_path"] in navigation
        assert row["status"] == (
            "archived" if row["matches"] else "not-in-pinned-capsules"
        )
        assert "benchmark original" in (ROOT / row["document"]).read_text()
    assert "remain deliberately withheld" in navigation
    assert "not public recovered inputs" in navigation


def test_bindings_resolve_to_verified_external_inputs():
    roots = {
        name: os.environ.get(f"BENCHMARK_{name.upper()}_ROOT")
        for name in ("evidence", "history", "collection")
    }
    if not any(roots.values()):
        pytest.skip("Canonical-data CI supplies verified external originals")
    assert all(roots.values())
    for row in bindings()["bindings"]:
        for match in row["matches"]:
            for member in match["members"]:
                assert (Path(roots[match["capsule"]]) / member).is_file(), member
        if not row["matches"]:
            assert all(
                not (Path(directory) / row["legacy_path"]).exists()
                for directory in roots.values()
            )


def test_remote_originals_and_complete_legacy_inventory():
    if os.environ.get("VERIFY_PROTOCOL_ORIGINALS") != "1":
        pytest.skip("Canonical-data CI verifies fixed-commit document originals")
    config = json.loads((ROOT / "BENCHMARK_PROTOCOLS.json").read_text())
    raw = fetch(config["manifest_url"], 2_000_000)
    assert hashlib.sha256(raw).hexdigest() == config["manifest_sha256"]
    manifest = json.loads(raw)
    assert len(manifest["files"]) == 5
    mapping = bindings()
    assert mapping["original_manifest"].endswith("/manifest.json")
    expected = set()
    for row in manifest["files"]:
        url = config["manifest_url"].rsplit("/", 1)[0] + "/snapshot/" + row["path"]
        original = fetch(url, row["bytes"])
        assert len(original) == row["bytes"]
        assert hashlib.sha256(original).hexdigest() == row["sha256"]
        page = (ROOT / row["path"]).read_text()
        assert "/snapshot/" + row["path"] in page
        expected.update(
            (row["path"], path)
            for path in re.findall(
                r"`(\.benchmarks/results/[^`\s]+)`", original.decode()
            )
        )
    assert expected == {
        (row["document"], row["legacy_path"]) for row in mapping["bindings"]
    }
