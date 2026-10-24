"""Historical planning notes cannot become current results or PDF identities."""

import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NAMES = (
    "TOP_TIER_PUSH_PLAN.md",
    "RESEARCH_UPGRADE_20260727.md",
    "progress.md",
    "findings.md",
    "task_plan.md",
)
SPEC = importlib.util.spec_from_file_location(
    "notes_capsule", ROOT / "scripts/fetch_mod_consumer_evidence.py"
)
CAPSULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CAPSULE)


def mapping():
    return json.loads((ROOT / "docs/notes_evidence_bindings.json").read_text())


def test_notes_preserve_methods_and_claim_limits():
    texts = {n: (ROOT / n).read_text() for n in NAMES}
    for text in texts.values():
        assert "Complete historical original" in text
        assert "NOT_M0_PROVEN" in text
        assert ".benchmarks/results/" not in text
    assert "## Required Baselines" in texts["TOP_TIER_PUSH_PLAN.md"]
    assert "## Seven-step boundary" in texts["RESEARCH_UPGRADE_20260727.md"]
    assert "## Shared-interface contract" in texts["RESEARCH_UPGRADE_20260727.md"]
    assert (
        "not benchmark baseline/candidate identities"
        in texts["RESEARCH_UPGRADE_20260727.md"]
    )
    assert "NO_GO" in texts["findings.md"]
    assert "localization_only" in texts["findings.md"]
    assert "simulation/model" in texts["progress.md"]
    assert "Historical measurements and generated paper" in texts["task_plan.md"]
    assert "current queue or current-main test result" in texts["task_plan.md"]
    assert not any(
        needle in texts[n]
        for n in ("progress.md", "findings.md", "task_plan.md")
        for needle in ("12,261.98", "32 passed", "4/4", "144 dpi")
    )


def test_legacy_navigation_and_different_pdf_not_recovered():
    data = mapping()
    assert len(data["bindings"]) == 3
    navigation = (ROOT / "docs/notes_evidence.md").read_text()
    for row in data["bindings"]:
        assert row["legacy_path"] in navigation
        assert row["status"] == "archived" and row["matches"]
        for match in row["matches"]:
            assert all(
                member == row["legacy_path"]
                or member.startswith(row["legacy_path"].rstrip("/") + "/")
                for member in match["members"]
            )
    pdf = data["historical_pdf"]
    assert pdf["status"] == "recorded-digest-not-in-pinned-capsules"
    assert pdf["recorded_sha256"] != pdf["known_different_pdf"]["sha256"]
    assert pdf["legacy_path"] in navigation
    assert "not a recovered" in navigation


def test_legacy_members_resolve_to_verified_inputs():
    roots = {
        n: os.environ.get(f"BENCHMARK_{n.upper()}_ROOT")
        for n in ("evidence", "history", "collection")
    }
    if not any(roots.values()):
        pytest.skip("Canonical-data CI supplies the verified input roots")
    assert all(roots.values())
    for row in mapping()["bindings"]:
        for match in row["matches"]:
            assert all(
                (Path(roots[match["capsule"]]) / member).is_file()
                for member in match["members"]
            )


def test_known_paper_digest_and_bounded_missing_identity():
    roots = {
        n: os.environ.get(f"BENCHMARK_{n.upper()}_ROOT")
        for n in ("evidence", "history", "collection", "research")
    }
    if not roots["research"]:
        pytest.skip("Canonical-data CI supplies verified paper and data inputs")
    assert all(roots.values())
    pdf = mapping()["historical_pdf"]
    current = pdf["known_different_pdf"]
    raw = (Path(roots["research"]) / current["path"]).read_bytes()
    assert len(raw) == current["bytes"]
    assert hashlib.sha256(raw).hexdigest() == current["sha256"]
    for directory in roots.values():
        for path in Path(directory).rglob("*"):
            if path.is_file():
                assert (
                    hashlib.sha256(path.read_bytes()).hexdigest()
                    != pdf["recorded_sha256"]
                )


def test_remote_originals_complete_and_legacy_inventory():
    if os.environ.get("VERIFY_PROTOCOL_ORIGINALS") != "1":
        pytest.skip("Canonical-data CI verifies fixed document originals")
    config = json.loads((ROOT / "BENCHMARK_NOTES.json").read_text())
    raw = CAPSULE.fetch(config["manifest_url"], 2_000_000)
    assert hashlib.sha256(raw).hexdigest() == config["manifest_sha256"]
    manifest = json.loads(raw)
    assert {r["path"] for r in manifest["files"]} == set(NAMES)
    prefix = config["manifest_url"].rsplit("/", 1)[0]
    expected = set()
    pdf = mapping()["historical_pdf"]
    for row in manifest["files"]:
        raw = CAPSULE.fetch(prefix + "/snapshot/" + row["path"], row["bytes"])
        assert len(raw) == row["bytes"]
        assert hashlib.sha256(raw).hexdigest() == row["sha256"]
        assert "/snapshot/" + row["path"] in (ROOT / row["path"]).read_text()
        text = raw.decode()
        expected.update(
            (row["path"], path)
            for path in re.findall(r"\.benchmarks/results/[^`\s]+", text)
        )
        if row["path"] in pdf["documents"]:
            assert pdf["recorded_sha256"] in text
        if row["path"] == "progress.md":
            assert pdf["legacy_path"] in text
    assert expected == {
        (r["document"], r["legacy_path"]) for r in mapping()["bindings"]
    }
