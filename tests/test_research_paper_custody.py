import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "paper_stage", ROOT / "scripts/stage_paper_review.py"
)
STAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STAGE)


def test_paper_outputs_not_tracked():
    paths = subprocess.check_output(
        ["git", "ls-files", "paper"], cwd=ROOT, text=True
    ).splitlines()
    assert not any(
        path.endswith((".pdf", ".log", ".csv", ".tex", "BUILD_TRANSCRIPT.txt"))
        or "/generated/" in path
        or "/paper_assets_latest/" in path
        for path in paths
    )


def fixture(tmp_path):
    evidence = tmp_path / "evidence"
    rows = []
    for name, raw in [
        (STAGE.MANUSCRIPT, b"synthetic TeX fixture"),
        ("references.bib", b"fixture"),
    ]:
        path = evidence / STAGE.PREFIX / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        rows.append(
            {
                "path": STAGE.PREFIX + name,
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    return evidence, {"files": rows}


def test_stage_rejects_corruption_before_writing(tmp_path):
    evidence, manifest = fixture(tmp_path)
    (evidence / STAGE.PREFIX / STAGE.MANUSCRIPT).write_bytes(b"corrupt")
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="checksum"):
        STAGE.stage(evidence, output, manifest)
    assert not output.exists()


def test_stage_rejects_output_reuse_and_unsafe_path(tmp_path):
    evidence, manifest = fixture(tmp_path)
    output = tmp_path / "output"
    STAGE.stage(evidence, output, manifest)
    with pytest.raises(ValueError, match="new"):
        STAGE.stage(evidence, output, manifest)
    manifest["files"][0]["path"] = "../escape"
    with pytest.raises(ValueError, match="Unsafe"):
        STAGE.stage(evidence, tmp_path / "other", manifest)


def test_stage_rejects_checkout_output(tmp_path):
    evidence, manifest = fixture(tmp_path)
    with pytest.raises(ValueError, match="external"):
        STAGE.stage(evidence, ROOT / "build/test-stage", manifest)


def test_verified_paper_inputs_and_links(tmp_path):
    directory = os.environ.get("BENCHMARK_RESEARCH_ROOT")
    if not directory:
        pytest.skip("Canonical-data CI supplies the verified research capsule")
    config = json.loads((ROOT / "BENCHMARK_RESEARCH.json").read_text())
    raw = STAGE.fetch(config["manifest_url"], 2_000_000)
    assert STAGE.digest(raw) == config["manifest_sha256"]
    manifest = json.loads(raw)
    assert len(manifest["files"]) == 48
    selected = STAGE.stage(Path(directory), tmp_path / "staged", manifest)
    manuscript = selected[STAGE.MANUSCRIPT].decode()
    for dependency in re.findall(r"\\input\{([^}]+)\}", manuscript):
        assert dependency in selected
    assert "references.bib" in selected
    assert not any(name.endswith(".py") or name == "Makefile" for name in selected)
    for name in manifest["scope"]["context"]:
        text = (ROOT / name).read_text()
        assert manifest["archive"]["url"] in text
        assert "snapshot/" + name in text
