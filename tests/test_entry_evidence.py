"""Entry documents preserve identity without duplicating historical scores."""

import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NAMES = (
    "README.md",
    "CHANGELOG.md",
    ".benchmarks/README.md",
    "docs/research_logic.md",
    "docs/runtime_fault_attribution_roadmap.md",
)


def test_entry_navigation_and_scoped_claims():
    texts = {n: (ROOT / n).read_text() for n in NAMES}
    for n, text in texts.items():
        assert "/snapshot/" + n in text
        assert "NOT_M0_PROVEN" in text
    readme = texts["README.md"]
    assert "NO_GO" in readme and ">=0.31.1,<0.32" in readme
    assert "kept local; not part" not in readme
    assert "1/10" not in readme and "0/10" not in readme
    assert "evidence-mod-consumers-20261023-v1/profiler.tar.gz" in readme
    assert "## 0.1.2" in texts["CHANGELOG.md"]
    assert "EventBus 1.0" in texts["CHANGELOG.md"]
    assert "/home/shuhao/" not in texts["CHANGELOG.md"]
    assert "not checked-in runs" in texts[".benchmarks/README.md"]
    assert "80.94" not in texts["docs/runtime_fault_attribution_roadmap.md"]
    assert "invalid long-context" in texts["docs/runtime_fault_attribution_roadmap.md"]


def test_entry_consumers_and_external_members():
    mapping = json.loads((ROOT / "docs/entry_evidence_bindings.json").read_text())
    assert len(mapping["bindings"]) == 8
    for row in mapping["bindings"]:
        assert row["status"] == "archived" and row["members"]
        assert all(
            p == row["legacy_path"]
            or p.startswith(row["legacy_path"].rstrip("/") + "/")
            for p in row["members"]
        )
    make = (ROOT / "Makefile").read_text()
    assert '"$(BENCHMARK_COLLECTION_ROOT)/.benchmarks/results/' in make
    assert 'readme = "README.md"' in (ROOT / "pyproject.toml").read_text()
    directory = os.environ.get("BENCHMARK_COLLECTION_ROOT")
    if directory:
        for row in mapping["bindings"]:
            assert all((Path(directory) / p).is_file() for p in row["members"])


def test_entry_originals_and_complete_legacy_inventory():
    if os.environ.get("VERIFY_PROTOCOL_ORIGINALS") != "1":
        pytest.skip("Canonical CI verifies remote originals")
    spec = importlib.util.spec_from_file_location(
        "entry_capsule", ROOT / "scripts/fetch_mod_consumer_evidence.py"
    )
    capsule = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(capsule)
    config = json.loads((ROOT / "BENCHMARK_ENTRY_DOCS.json").read_text())
    raw = capsule.fetch(config["manifest_url"], 2_000_000)
    assert hashlib.sha256(raw).hexdigest() == config["manifest_sha256"]
    manifest = json.loads(raw)
    assert {r["path"] for r in manifest["files"]} == set(NAMES)
    prefix = config["manifest_url"].rsplit("/", 1)[0]
    expected = set()
    for row in manifest["files"]:
        raw = capsule.fetch(prefix + "/snapshot/" + row["path"], row["bytes"])
        assert len(raw) == row["bytes"]
        assert hashlib.sha256(raw).hexdigest() == row["sha256"]
        expected.update(
            (row["path"], p)
            for p in re.findall(r"\.benchmarks/results/[^`\s]+", raw.decode())
        )
    mapping = json.loads((ROOT / "docs/entry_evidence_bindings.json").read_text())
    assert expected == {(r["document"], r["legacy_path"]) for r in mapping["bindings"]}
