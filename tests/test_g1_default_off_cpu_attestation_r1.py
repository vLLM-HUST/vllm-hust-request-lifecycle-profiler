from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ATTESTATION_PATH = (
    REPO_ROOT
    / "contracts"
    / "p1"
    / "g1-default-off-cpu-implementation-attestation.r1.json"
)
EXPECTED_STATUS = (
    "EXECUTABLE_ATTESTATION_CANDIDATE_READY_FOR_INDEPENDENT_RUNTIME_OWNER_"
    "ITEMS_6_8_REVIEW"
)


def load_attestation() -> dict[str, object]:
    return json.loads(ATTESTATION_PATH.read_text())


def git_blob(repo: Path, commit: str, path: str) -> bytes:
    return subprocess.check_output(
        ["git", "show", f"{commit}:{path}"],
        cwd=repo,
    )


def assert_commit_is_local_ancestor(repo: Path, commit: str) -> None:
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
        cwd=repo,
        check=True,
    )


def runtime_repo(record: dict[str, object]) -> Path:
    override = os.environ.get("VLLM_HUST_G1_SRC", "").strip()
    if override:
        return Path(override)
    return Path(record["source_baselines"]["runtime"]["local_worktree"])


def profiler_history_repo() -> Path:
    override = os.environ.get("RLP_G1_PROFILER_HISTORY_SRC", "").strip()
    if not override:
        pytest.skip(
            "set RLP_G1_PROFILER_HISTORY_SRC to a checkout containing PR #10 history"
        )
    return Path(override)


def test_r1_binds_exact_local_implementation_commits() -> None:
    record = load_attestation()
    baselines = record["source_baselines"]
    runtime = baselines["runtime"]
    profiler = baselines["profiler"]

    assert runtime["implementation_commit"] == (
        "43509bcf1bd6db470537c1400fce390580f0603b"
    )
    assert profiler["implementation_commit"] == (
        "b2a28988ba9610c23d95c955e006f7ba92a3c750"
    )
    assert runtime["remote_publication"] is False
    assert profiler["remote_publication"] is False
    assert_commit_is_local_ancestor(
        runtime_repo(record), runtime["implementation_commit"]
    )
    assert_commit_is_local_ancestor(
        profiler_history_repo(), profiler["implementation_commit"]
    )


def test_r1_hashes_match_both_bound_commit_blob_sets() -> None:
    record = load_attestation()
    baselines = record["source_baselines"]
    groups = (
        (
            runtime_repo(record),
            baselines["runtime"]["implementation_commit"],
            (*record["runtime_source_files"], *record["runtime_test_files"]),
        ),
        (
            profiler_history_repo(),
            baselines["profiler"]["implementation_commit"],
            (*record["profiler_source_files"], *record["profiler_test_files"]),
        ),
    )
    for repo, commit, artifacts in groups:
        for artifact in artifacts:
            digest = hashlib.sha256(
                git_blob(repo, commit, artifact["path"])
            ).hexdigest()
            assert digest == artifact["sha256"]


def test_r1_keeps_authority_and_every_downstream_gate_closed() -> None:
    record = load_attestation()

    assert record["status"] == EXPECTED_STATUS
    assert record["authority_effect"] == "none"
    assert record["active_configuration_boundary"] == {
        "communication_mode": "none",
        "runtime_core": "OffloadingConnector/TieringOffloadingSpec",
        "recompute_scheduler_enable": False,
        "runtime_activation_authorized": False,
        "source_conformance_seam_only": True,
    }
    assert all(value is False for value in record["closed_gates"].values())
    for item in record["runtime_owner_review_items"].values():
        assert item["status"] == (
            "candidate_ready_for_independent_runtime_owner_review_not_approved"
        )


def test_r1_binds_real_model_entry_rosters_and_activation_stays_false() -> None:
    record = load_attestation()
    runtime = record["source_baselines"]["runtime"]
    runtime_repo_path = runtime_repo(record)
    commit = runtime["implementation_commit"]
    profile_source = git_blob(
        runtime_repo_path, commit, "vllm/v1/kv_recovery_profile.py"
    ).decode()
    mrv1_source = git_blob(
        runtime_repo_path, commit, "vllm/v1/worker/gpu_model_runner.py"
    ).decode()
    mrv2_source = git_blob(
        runtime_repo_path, commit, "vllm/v1/worker/gpu/model_runner.py"
    ).decode()

    assert "KV_RECOVERY_RUNTIME_ACTIVATION_AUTHORIZED = False" in profile_source
    assert mrv1_source.index(
        "self.observe_kv_recovery_first_compute(scheduler_output)"
    ) < mrv1_source.index("model_output = self._model_forward(")
    assert (
        mrv2_source.count(
            "self.kv_connector.observe_kv_recovery_first_compute(scheduler_output)"
        )
        == 2
    )


def test_r1_records_exact_green_gates_and_honest_diagnostics() -> None:
    record = load_attestation()
    results = {
        entry["scope"]: entry["result"] for entry in record["executable_results"]
    }

    assert results[
        "runtime_focused_default_off_CPU_and_real_forward_observer"
    ].startswith("81 passed")
    assert results["runtime_real_forward_observer_isolated_CPU"].startswith("4 passed")
    assert results["profiler_complete_suite_with_actual_runtime_ABI"].startswith(
        "181 passed"
    )
    diagnostic = record["non_gating_diagnostics"][0]
    assert diagnostic["result"].startswith("5 failed, 34 passed, 2 skipped")
    assert diagnostic["classification"] == "not_used_as_passing_evidence"
    assert diagnostic["changed_G1_stack_frames_in_failures"] is False
    assert record["next_execution_order"][0] == (
        "request_independent_runtime_owner_Items_6_8_review_of_this_exact_candidate"
    )
