from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ATTESTATION_PATH = (
    REPO_ROOT
    / "contracts"
    / "p1"
    / "g1-default-off-cpu-implementation-attestation.r0.json"
)


def git_blob_sha256(commit: str, path: str) -> str:
    blob = subprocess.check_output(
        ["git", "show", f"{commit}:{path}"],
        cwd=REPO_ROOT,
    )
    return hashlib.sha256(blob).hexdigest()


def load_attestation() -> dict[str, object]:
    return json.loads(ATTESTATION_PATH.read_text())


def test_attestation_binds_exact_local_implementation_commits() -> None:
    record = load_attestation()
    baselines = record["source_baselines"]
    profiler = baselines["profiler"]
    runtime = baselines["runtime"]

    assert profiler["implementation_commit"] == (
        "091afd76557a44f9b7e2d795b5f11200ad0f552f"
    )
    assert runtime["implementation_commit"] == (
        "b8d8869e0507dc50b6cf293de58dce202fe2db3e"
    )
    assert profiler["remote_publication"] is False
    assert runtime["remote_publication"] is False
    subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            profiler["implementation_commit"],
            "HEAD",
        ],
        cwd=REPO_ROOT,
        check=True,
    )


def test_attestation_profiler_hashes_match_bound_commit_blobs() -> None:
    record = load_attestation()
    implementation_commit = record["source_baselines"]["profiler"][
        "implementation_commit"
    ]

    for artifact in [
        *record["profiler_source_files"],
        *record["profiler_test_files"],
    ]:
        assert (
            git_blob_sha256(implementation_commit, artifact["path"])
            == artifact["sha256"]
        )


def test_attestation_is_explicitly_partial_and_keeps_every_gate_closed() -> None:
    record = load_attestation()
    review = record["runtime_owner_review_items"]

    assert record["authority_effect"] == "none"
    assert record["status"].startswith("PARTIAL_EXECUTABLE_ATTESTATION")
    assert review["item_6"]["status"].endswith("not_submitted_for_approval")
    assert review["item_7"]["status"] == "not_ready_for_approval"
    assert review["item_8"]["status"] == "partial_not_ready_for_approval"
    assert all(value is False for value in record["closed_gates"].values())


def test_attestation_records_exact_CPU_results_and_remaining_order() -> None:
    record = load_attestation()
    results = {
        entry["scope"]: entry["result"] for entry in record["executable_results"]
    }

    assert results["runtime_focused_default_off_CPU"].startswith("72 passed")
    assert results["actual_runtime_ABI_cross_repository_CPU"].startswith("5 passed")
    assert results["profiler_complete_suite_with_actual_runtime_ABI"].startswith(
        "169 passed"
    )
    assert record["next_execution_order"][-1] == (
        "only_then_request_runtime_owner_Items_6_8_review"
    )
