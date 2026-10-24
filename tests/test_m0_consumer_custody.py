"""M0 historical inputs cannot silently become fresh/partial results."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

from vllm_request_lifecycle_profiler import issue19_m0
from vllm_request_lifecycle_profiler.evidence_paths import fresh_external_output

ROOT = Path(__file__).resolve().parents[1]


def module(path):
    spec = importlib.util.spec_from_file_location("custody_driver", ROOT / path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.mark.parametrize(
    "kind", ["relative", "checkout", "existing", "input", "symlink"]
)
def test_output_rejects_unsafe_paths(tmp_path, kind):
    source = tmp_path / "input"
    source.mkdir()
    link = tmp_path / "link"
    link.symlink_to(source, target_is_directory=True)
    path = {
        "relative": Path("new-output"),
        "checkout": ROOT / "new-output",
        "existing": source,
        "input": source / "new-output",
        "symlink": link / "new-output",
    }[kind]
    with pytest.raises(ValueError):
        fresh_external_output(path, inputs=(source,))
    assert list(source.iterdir()) == []


def test_preflight_rejects_reuse_before_workload(monkeypatch, tmp_path):
    def unexpected(*args, **kwargs):
        pytest.fail("invalid output must stop before workload or environment access")

    monkeypatch.setattr(issue19_m0, "build_oasst1_repetitions", unexpected)
    with pytest.raises(ValueError, match="new directory"):
        issue19_m0.main(["--output-dir", str(tmp_path)])
    with pytest.raises(SystemExit):
        issue19_m0.parse_args([])
    assert "ISSUE19_PREFLIGHT_OUTPUT" in (ROOT / "Makefile").read_text()


def test_missing_private_input_never_writes_result(tmp_path):
    driver = module(".benchmarks/run_m0_development_validation.py")
    private, collection, output = [
        tmp_path / n for n in ("private", "collection", "output")
    ]
    private.mkdir()
    collection.mkdir()
    with pytest.raises(ValueError, match="missing or ambiguous historical run"):
        driver.run(
            [
                "--g4-runs-root",
                str(private),
                "--collection-root",
                str(collection),
                "--output-dir",
                str(output),
            ]
        )
    assert not output.exists()


def test_fixture_only_derivation_is_isolated_and_labeled(tmp_path):
    driver = module(".benchmarks/run_m0_development_validation.py")
    private, collection, output = [
        tmp_path / n for n in ("private", "collection", "output")
    ]
    private.mkdir()
    collection.mkdir()
    for prefix in (
        "f4b1b083",
        "0fe82cc1",
        "d20f2126",
        "eaa94f8b",
        "73d47651",
        "ababc337",
        "7d36ef9f",
        "c04e4681",
        "b2e2a7cf",
        "24b0508b",
        "adf18208",
        "fb81d458",
    ):
        run = private / prefix
        run.mkdir()
        (run / "pressure_client.out").write_text('{"label":"req0","total_s":1}\n')
        events = [
            {
                "record_type": "recovery_event",
                "runtime_request_id": "synthetic",
                "stage": stage,
                "timestamp_ns": ts,
            }
            for stage, ts in (("preempt", 1), ("first_prefill_or_decode", 1000001))
        ]
        (run / "trace.rlp-kv-recovery.fixture.jsonl").write_text(
            "\n".join(json.dumps(e) for e in events) + "\n"
        )
    csv = (
        collection
        / ".benchmarks/results/npu6_runtime_hooks_concurrency_sweep/runtime_internal_spans.csv"
    )
    csv.parent.mkdir(parents=True)
    csv.write_text(
        "phase,assigned_concurrency,chain_id,prefill,decode\n"
        "measured,1,a,10,10\nmeasured,2,b,100,10\nmeasured,3,c,11,10\n"
    )
    before = {
        p: p.read_bytes()
        for r in (private, collection)
        for p in r.rglob("*")
        if p.is_file()
    }
    args = [
        "--g4-runs-root",
        str(private),
        "--collection-root",
        str(collection),
        "--output-dir",
        str(output),
    ]
    driver.run(args)
    data = json.loads((output / "validation.json").read_text())
    assert data["_provenance"]["status"] == "NOT_M0_PROVEN"
    assert data["_provenance"]["blind_scored"] is False
    assert "heuristic" in data["_provenance"]["identity_limit"]
    assert all(p.read_bytes() == raw for p, raw in before.items())
    with pytest.raises(ValueError, match="new directory"):
        driver.run(args)
    csv.write_text(csv.read_text().replace("measured,3,c,11,10\n", ""))
    args[-1] = str(tmp_path / "incomplete")
    with pytest.raises(ValueError, match="missing measured concurrency 1/3"):
        driver.run(args)
    assert not (tmp_path / "incomplete").exists()


def test_m0_documents_preserve_protocol_and_absence_boundary():
    pipeline = (ROOT / "docs/m0_evaluation_pipeline.md").read_text()
    preflight = (ROOT / "docs/issue19_m0_preflight.md").read_text()
    assert "0.912" not in pipeline and "5 passed" not in pipeline
    assert "max-total heuristic" in pipeline and "NOT_M0_PROVEN" in pipeline
    for value in ("10880", "2147483648", "lifecycle_reconcile=false", "NO_GO"):
        assert value in preflight
    assert "ISSUE19_PREFLIGHT_OUTPUT" in preflight
    mapping = json.loads((ROOT / "docs/m0_consumer_evidence.json").read_text())
    assert [r["status"] for r in mapping["bindings"]] == [
        "not-in-four-pinned-capsules",
        "output-not-archival-input",
        "not-in-four-pinned-capsules",
        "archived",
    ]
    collection = os.environ.get("BENCHMARK_COLLECTION_ROOT")
    if collection:
        for row in mapping["bindings"][-1]["matches"][0]["members"]:
            raw = (Path(collection) / row["path"]).read_bytes()
            assert len(raw) == row["bytes"]
            assert hashlib.sha256(raw).hexdigest() == row["sha256"]


def test_m0_remote_originals_and_bounded_missing_inputs():
    if os.environ.get("VERIFY_PROTOCOL_ORIGINALS") != "1":
        pytest.skip("Canonical CI checks fixed remote originals and manifests")
    fetch = module("scripts/fetch_mod_consumer_evidence.py").fetch
    config = json.loads((ROOT / "BENCHMARK_M0_CONSUMERS.json").read_text())
    raw = fetch(config["manifest_url"], 2_000_000)
    assert hashlib.sha256(raw).hexdigest() == config["manifest_sha256"]
    manifest = json.loads(raw)
    assert len(manifest["files"]) == 3
    for row in manifest["files"]:
        raw = fetch(
            config["manifest_url"].rsplit("/", 1)[0] + "/snapshot/" + row["path"],
            row["bytes"],
        )
        assert len(raw) == row["bytes"]
        assert hashlib.sha256(raw).hexdigest() == row["sha256"]
    mapping = json.loads((ROOT / "docs/m0_consumer_evidence.json").read_text())
    for name in ("EVIDENCE", "HISTORY", "COLLECTION", "RESEARCH"):
        config = json.loads((ROOT / f"BENCHMARK_{name}.json").read_text())
        raw = fetch(config["manifest_url"], 2_000_000)
        assert hashlib.sha256(raw).hexdigest() == config["manifest_sha256"]
        paths = [r["path"] for r in json.loads(raw)["files"]]
        for row in mapping["bindings"]:
            if row["status"] == "not-in-four-pinned-capsules":
                assert not any(
                    p == row["legacy_path"]
                    or p.startswith(row["legacy_path"].rstrip("/") + "/")
                    for p in paths
                )
