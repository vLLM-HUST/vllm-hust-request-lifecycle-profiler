from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ATTESTATION_PATH = (
    REPO_ROOT
    / "contracts"
    / "p1"
    / "g1-default-off-cpu-implementation-attestation.r2.json"
)
R1_PATH = (
    REPO_ROOT
    / "contracts"
    / "p1"
    / "g1-default-off-cpu-implementation-attestation.r1.json"
)
EXPECTED_STATUS = (
    "REMEDIATED_EXECUTABLE_ATTESTATION_CANDIDATE_READY_FOR_INDEPENDENT_"
    "RUNTIME_OWNER_ITEMS_6_8_RE_REVIEW"
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


def test_r2_supersedes_but_does_not_mutate_r1() -> None:
    record = load_attestation()

    assert hashlib.sha256(R1_PATH.read_bytes()).hexdigest() == (
        "5d15e1b231c60fd18d5a42c849eed2c2c1fb48ecc4b75c949223cf4224c06048"
    )
    assert record["supersedes_for_future_review"] == {
        "path": "contracts/p1/g1-default-off-cpu-implementation-attestation.r1.json",
        "sha256": ("5d15e1b231c60fd18d5a42c849eed2c2c1fb48ecc4b75c949223cf4224c06048"),
        "historical_record_remains_immutable": True,
    }


def test_r2_binds_exact_remediation_commits_and_review_anchor() -> None:
    record = load_attestation()
    baselines = record["source_baselines"]
    runtime = baselines["runtime"]
    profiler = baselines["profiler"]

    assert runtime["implementation_commit"] == (
        "5f7872976bd56a0861bb0072eaac68260ba7d578"
    )
    assert profiler["conformance_commit"] == (
        "f43473e78e3636e079518e19eb3ac3aeea21d8fc"
    )
    assert_commit_is_local_ancestor(
        runtime_repo(record), runtime["implementation_commit"]
    )
    assert_commit_is_local_ancestor(REPO_ROOT, profiler["conformance_commit"])
    assert baselines["shared_workloads"] == {
        "repository": "intellistream/llm-serving-workloads",
        "pinned_commit": "76e24c85bcab76ecfabb831c9444002b6efffd58",
    }
    assert record["remediation_target"]["review_thread_id"] == ("PRRT_kwDORq6LNc6WbsqA")
    assert record["remediation_target"]["review_state"] == "CHANGES_REQUESTED"


def test_r2_hashes_match_both_bound_commit_blob_sets() -> None:
    record = load_attestation()
    baselines = record["source_baselines"]
    groups = (
        (
            runtime_repo(record),
            baselines["runtime"]["implementation_commit"],
            (
                *record["runtime_source_files"],
                *record["runtime_test_and_validation_files"],
            ),
        ),
        (
            REPO_ROOT,
            baselines["profiler"]["conformance_commit"],
            (*record["profiler_source_files"], *record["profiler_test_files"]),
        ),
    )
    for repo, commit, artifacts in groups:
        for artifact in artifacts:
            digest = hashlib.sha256(
                git_blob(repo, commit, artifact["path"])
            ).hexdigest()
            assert digest == artifact["sha256"]


def test_r2_binds_completion_fence_before_explicit_discard() -> None:
    record = load_attestation()
    runtime = record["source_baselines"]["runtime"]
    runtime_repo_path = runtime_repo(record)
    commit = runtime["implementation_commit"]
    worker_source = git_blob(
        runtime_repo_path,
        commit,
        "vllm/distributed/kv_transfer/kv_connector/v1/offloading/worker.py",
    ).decode()
    common_source = git_blob(
        runtime_repo_path,
        commit,
        "vllm/distributed/kv_transfer/kv_connector/v1/offloading/common.py",
    ).decode()

    handle_preemptions = worker_source[
        worker_source.index("    def handle_preemptions(") : worker_source.index(
            "    def start_kv_transfers("
        )
    ]
    assert handle_preemptions.index("_prepare_kv_recovery_wait(") < (
        handle_preemptions.index("self.worker.wait(")
    )
    assert handle_preemptions.index("self.worker.wait(") < (
        handle_preemptions.index("_record_kv_recovery_wait(")
    )
    assert handle_preemptions.index("_record_kv_recovery_wait(") < (
        handle_preemptions.index("kv_recovery_jobs_to_invalidate")
    )
    assert "invalidate_transfers(kv_connector_metadata.jobs_to_flush)" not in (
        handle_preemptions
    )
    assert "kv_recovery_jobs_to_invalidate: set[int] | None = None" in common_source


def test_r2_keeps_disabled_path_clock_free_and_activation_closed() -> None:
    record = load_attestation()
    runtime = record["source_baselines"]["runtime"]
    runtime_repo_path = runtime_repo(record)
    commit = runtime["implementation_commit"]
    profile_source = git_blob(
        runtime_repo_path, commit, "vllm/v1/kv_recovery_profile.py"
    ).decode()
    mrv1_connector = git_blob(
        runtime_repo_path,
        commit,
        "vllm/v1/worker/kv_connector_model_runner_mixin.py",
    ).decode()
    mrv2_connector = git_blob(
        runtime_repo_path, commit, "vllm/v1/worker/gpu/kv_connector.py"
    ).decode()

    assert "KV_RECOVERY_RUNTIME_ACTIVATION_AUTHORIZED = False" in profile_source
    assert "monotonic_ns" not in mrv1_connector
    assert "monotonic_ns" not in mrv2_connector
    assert record["status"] == EXPECTED_STATUS
    assert record["authority_effect"] == "none"
    assert all(value is False for value in record["closed_gates"].values())
    assert record["publication_scope"]["review_only"] is True
    assert record["publication_scope"]["activation_effect"] == "none"


def test_r2_records_green_gates_and_honest_baseline_diagnostics() -> None:
    record = load_attestation()
    results = {
        entry["scope"]: entry["result"] for entry in record["executable_results"]
    }

    assert results[
        "runtime_focused_default_off_CPU_and_real_forward_observer"
    ].startswith("89 passed")
    assert results["actual_runtime_ABI_cross_repository_CPU"].startswith("16 passed")
    assert results[
        "profiler_complete_suite_with_actual_runtime_ABI_and_shared_workloads"
    ].startswith("187 passed")
    assert "all applicable hooks passed" in results["runtime_changed_file_pre_commit"]
    diagnostics = {entry["scope"]: entry for entry in record["non_gating_diagnostics"]}
    offloading = diagnostics["complete_offloading_connector_CPU_directory"]
    assert offloading["result"].startswith("13 failed, 150 passed, 2 skipped")
    assert "reproduces_at_audited_base_f229ba7" in offloading["classification"]
    assert offloading["changed_G1_stack_frames_in_failures"] is False
    for item in record["runtime_owner_review_items"].values():
        assert item["status"] == (
            "remediated_candidate_ready_for_independent_runtime_owner_"
            "re_review_not_approved"
        )
