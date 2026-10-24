"""Protect runbook methods, archival bindings and fresh-output examples."""

import hashlib
import importlib.util
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NAMES = (
    "live_fault_matrix_plan",
    "next_agent_task",
    "blind_attribution_execution",
    "npu6_trace_probe_runbook",
)
SPEC = importlib.util.spec_from_file_location(
    "runbook_capsule", ROOT / "scripts/fetch_mod_consumer_evidence.py"
)
CAPSULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CAPSULE)


def mapping():
    return json.loads((ROOT / "docs/runbook_evidence_bindings.json").read_text())


def test_methods_and_scoped_failure_preserved():
    texts = {n: (ROOT / "docs" / f"{n}.md").read_text() for n in NAMES}
    assert all("Complete historical original" in text for text in texts.values())
    assert "NOT_M0_PROVEN" in texts["next_agent_task"]
    assert "NO_GO" in texts["next_agent_task"]
    assert "1/10" not in texts["next_agent_task"]
    assert "12299.08" not in texts["live_fault_matrix_plan"]
    assert "remain invalid" in texts["live_fault_matrix_plan"]
    assert "0.60 dominance and 0.40 residual" in texts["blind_attribution_execution"]
    assert "2026082701" in texts["blind_attribution_execution"]
    assert "not current READY" in texts["npu6_trace_probe_runbook"]
    assert "Both markers present" in texts["npu6_trace_probe_runbook"]
    assert "one-to-one association" in texts["npu6_trace_probe_runbook"]
    for n in ("blind_attribution_execution", "npu6_trace_probe_runbook"):
        for block in re.findall(r"```bash\n(.*?)```", texts[n], re.DOTALL):
            subprocess.run(["bash", "-n"], input=block, text=True, check=True)
        assert "--output-dir .benchmarks/results" not in texts[n]
        assert "--output .benchmarks/results" not in texts[n]
    assert "${PROBE_OUTPUT:?" in texts["npu6_trace_probe_runbook"]
    assert "${DEVELOPMENT_OUTPUT:?" in texts["blind_attribution_execution"]


def test_input_output_roles_and_navigation():
    rows = mapping()["bindings"]
    assert len(rows) == 9
    assert len({(r["document"], r["legacy_path"]) for r in rows}) == len(rows)
    assert sum(r["role"] == "fresh-output-example" for r in rows) == 3
    navigation = (ROOT / "docs/runbook_evidence.md").read_text()
    for row in rows:
        assert row["legacy_path"] in navigation
        assert row["status"] == (
            "output-not-archival-input"
            if row["role"] == "fresh-output-example"
            else "archived"
            if row["matches"]
            else "not-in-pinned-capsules"
        )
        for match in row["matches"]:
            assert all(
                p == row["legacy_path"]
                or p.startswith(row["legacy_path"].rstrip("/") + "/")
                for p in match["members"]
            )
    assert "not recovered" in navigation


def test_members_against_verified_capsules():
    roots = {
        n: os.environ.get(f"BENCHMARK_{n.upper()}_ROOT")
        for n in ("evidence", "history", "collection")
    }
    if not any(roots.values()):
        pytest.skip("Canonical-data CI supplies all verified capsules")
    assert all(roots.values())
    for row in mapping()["bindings"]:
        for match in row["matches"]:
            assert all(
                (Path(roots[match["capsule"]]) / p).is_file() for p in match["members"]
            )
        if not row["matches"] and row["legacy_path"].startswith(".benchmarks/"):
            assert all(
                not (Path(directory) / row["legacy_path"]).exists()
                for directory in roots.values()
            )


def test_remote_original_bytes_and_inventory():
    if os.environ.get("VERIFY_PROTOCOL_ORIGINALS") != "1":
        pytest.skip("Canonical-data CI verifies fixed document originals")
    config = json.loads((ROOT / "BENCHMARK_RUNBOOKS.json").read_text())
    raw = CAPSULE.fetch(config["manifest_url"], 2_000_000)
    assert hashlib.sha256(raw).hexdigest() == config["manifest_sha256"]
    manifest = json.loads(raw)
    assert {r["path"] for r in manifest["files"]} == {f"docs/{n}.md" for n in NAMES}
    expected = set()
    prefix = config["manifest_url"].rsplit("/", 1)[0]
    for row in manifest["files"]:
        data = CAPSULE.fetch(prefix + "/snapshot/" + row["path"], row["bytes"])
        assert len(data) == row["bytes"]
        assert hashlib.sha256(data).hexdigest() == row["sha256"]
        assert "/snapshot/" + row["path"] in (ROOT / row["path"]).read_text()
        expected.update(
            (row["path"], path)
            for path in re.findall(r"\.benchmarks/results/[^`\s]+", data.decode())
        )
    expected.add(
        (
            "docs/npu6_trace_probe_runbook.md",
            "/tmp/codex-vllm-request-lifecycle-profiler-npu6-trace.jsonl",
        )
    )
    assert expected == {
        (r["document"], r["legacy_path"]) for r in mapping()["bindings"]
    }
