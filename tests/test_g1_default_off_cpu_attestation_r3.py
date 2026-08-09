from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
R1_PATH = (
    REPO_ROOT
    / "contracts"
    / "p1"
    / "g1-default-off-cpu-implementation-attestation.r1.json"
)
R2_PATH = (
    REPO_ROOT
    / "contracts"
    / "p1"
    / "g1-default-off-cpu-implementation-attestation.r2.json"
)
R3_PATH = (
    REPO_ROOT
    / "contracts"
    / "p1"
    / "g1-default-off-cpu-implementation-attestation.r3.json"
)


def load_r3() -> dict[str, object]:
    return json.loads(R3_PATH.read_text())


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_commit_is_ancestor(commit: str) -> None:
    available = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
    )
    if available.returncode != 0:
        pytest.skip(
            "the publication commit is unavailable in this shallow checkout; "
            "fetch complete parent history to validate ancestry"
        )
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
        cwd=REPO_ROOT,
        check=True,
    )


def runtime_repo() -> Path:
    override = os.environ.get("VLLM_HUST_G1_SRC", "").strip()
    if not override:
        pytest.skip("set VLLM_HUST_G1_SRC for exact runtime reconciliation")
    repository = Path(override).resolve()
    if (
        not (repository / ".git").exists()
        and not (repository / "vllm" / "v1" / "kv_recovery_profile.py").is_file()
    ):
        pytest.fail("VLLM_HUST_G1_SRC is not an exact G1 runtime checkout")
    return repository


def test_r3_preserves_r1_r2_and_reconciles_the_portability_delta() -> None:
    record = load_r3()

    assert sha256(R1_PATH) == (
        "5d15e1b231c60fd18d5a42c849eed2c2c1fb48ecc4b75c949223cf4224c06048"
    )
    assert sha256(R2_PATH) == (
        "680eb00f7e71cbc7aa4e74b97ebb13b29062d0501d98f2b877a80f3d728b9b68"
    )
    assert record["supersedes_for_future_reproducibility_review"]["sha256"] == (
        "680eb00f7e71cbc7aa4e74b97ebb13b29062d0501d98f2b877a80f3d728b9b68"
    )
    mismatch = record["reconciled_portability_delta"]
    assert mismatch["r2_recorded_test_sha256"] == (
        "c15bd08580f95f855fa695bf7b579808311510464804983e3f4d07f1bcf88970"
    )
    assert mismatch["merged_test_sha256"] == (
        "d6ef9d9768e1b8566857150fba03ea6e0b8b104d4e4776e070d08e56aa286bd3"
    )
    assert mismatch["r1_or_r2_bytes_mutated"] is False


def test_r3_binds_the_exact_parent_publication_approval_and_merge() -> None:
    record = load_r3()
    publication = record["profiler_parent_publication"]
    approval = publication["approval"]

    assert publication["reviewed_head"] == ("5558d213f94f2fb910c1e1e8685f555556867cda")
    assert publication["merge_commit"] == ("7a77703e916eebe41fe1b6c0993aeae7cf999240")
    assert_commit_is_ancestor(publication["merge_commit"])
    assert publication["merge_method"] == "squash"
    assert publication["reviewed_head_is_merge_ancestor"] is False
    assert publication["merged_tree_revalidates_r2_profiler_blobs"] is True
    assert (
        publication["merged_tree_does_not_replace_r1_historical_blob_identity"] is True
    )
    assert approval == {
        "review_id": 4860889814,
        "review_node_id": "PRR_kwDOTUmGYs8AAAABIbtK1g",
        "state": "APPROVED",
        "submitted_at": "2026-08-05T04:08:45Z",
        "scope": "default_off_profiler_parent_publication_merge_only",
    }
    assert publication["merged_at"] == "2026-08-05T04:08:54Z"


def test_r3_portable_validation_files_match_the_merged_tree() -> None:
    record = load_r3()

    for artifact in record["portable_validation_files"]:
        assert sha256(REPO_ROOT / artifact["path"]) == artifact["sha256"]

    checkout = record["portable_checkout_contract"]
    assert checkout["profiler_PR_10_history_checkout_env"] == (
        "RLP_G1_PROFILER_HISTORY_SRC"
    )
    assert checkout["network_access_from_tests"] is False


def test_r3_still_binds_the_exact_runtime_remediation_commit() -> None:
    record = load_r3()
    runtime = record["runtime_review_state"]
    repository = runtime_repo()

    subprocess.run(
        ["git", "cat-file", "-e", f"{runtime['head_commit']}^{{commit}}"],
        cwd=repository,
        check=True,
    )
    assert runtime["head_commit"] == ("5f7872976bd56a0861bb0072eaac68260ba7d578")
    assert runtime["review_decision"] == "CHANGES_REQUESTED"
    assert runtime["draft"] is True
    assert runtime["review_thread_resolved"] is False


def test_r3_does_not_expand_approval_or_activation_scope() -> None:
    record = load_r3()

    assert record["authority_effect"] == (
        "profiler_parent_publication_merge_only_no_runtime_authority"
    )
    assert record["active_configuration_boundary"] == {
        "communication_mode": "none",
        "runtime_core": "OffloadingConnector/TieringOffloadingSpec",
        "recompute_scheduler_enable": False,
        "runtime_activation_authorized": False,
        "source_conformance_seam_only": True,
    }
    assert record["runtime_owner_items_6_8_status"] == (
        "remediated_candidate_not_explicitly_approved"
    )
    assert all(value is False for value in record["closed_gates"].values())
