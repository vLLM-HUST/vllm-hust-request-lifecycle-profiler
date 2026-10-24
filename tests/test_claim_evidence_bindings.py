"""Claim navigation binds to verified external originals, never local results."""

import hashlib
import json
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_ledger_projection_boundaries():
    ledger = (ROOT / "docs/claim_ledger.md").read_text()
    rows = [
        line.split("|")[1:-1] for line in ledger.splitlines() if line.startswith("| ")
    ][2:]
    assert len(rows) == 22
    assert "NOT_M0_PROVEN" in ledger
    assert "NO_GO" in ledger
    assert "G1/G4 local inputs remain unavailable" in ledger
    assert all(not re.search(r"\d+\.\d+|\d+/\d+", row[1]) for row in rows)
    bindings = json.loads((ROOT / "docs/claim_evidence_bindings.json").read_text())
    for entry in bindings["bindings"]:
        assert 1 <= entry["claim"] <= len(rows)
        assert entry["legacy_path"].startswith(".benchmarks/results/")
        assert entry["status"] == (
            "archived" if entry["matches"] else "not-in-pinned-capsules"
        )
        for match in entry["matches"]:
            assert match["capsule"] in {"evidence", "history", "collection"}
            assert match["members"]


def test_bindings_against_verified_originals():
    roots = {
        name: os.environ.get(f"BENCHMARK_{name.upper()}_ROOT")
        for name in ("evidence", "history", "collection")
    }
    if not any(roots.values()):
        pytest.skip("Canonical-data CI supplies all three verified capsules")
    assert all(roots.values()), "Supply all three verified external roots"
    roots = {name: Path(path).resolve() for name, path in roots.items()}
    assert all(ROOT != path and ROOT not in path.parents for path in roots.values())
    bindings = json.loads((ROOT / "docs/claim_evidence_bindings.json").read_text())
    original = bindings["original_ledger"]
    raw = (roots[original["capsule"]] / original["path"]).read_bytes()
    assert len(raw) == original["bytes"]
    assert hashlib.sha256(raw).hexdigest() == original["sha256"]
    old = [
        line.split("|")[1:-1]
        for line in raw.decode().splitlines()
        if line.startswith("| ")
    ][2:]
    new = [
        line.split("|")[1:-1]
        for line in (ROOT / "docs/claim_ledger.md").read_text().splitlines()
        if line.startswith("| ")
    ][2:]
    for i, (before, after) in enumerate(zip(old, new)):
        assert before[0] == after[0]
        if i != 9:  # Previously migrated overhead row has its maintained boundary.
            assert before[-1] == after[-1]
    for entry in bindings["bindings"]:
        for match in entry["matches"]:
            for member in match["members"]:
                assert (roots[match["capsule"]] / member).is_file(), member
        if not entry["matches"]:
            assert all(
                not (root / entry["legacy_path"]).exists() for root in roots.values()
            )
