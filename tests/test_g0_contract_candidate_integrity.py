from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
P1 = REPOSITORY_ROOT / "contracts" / "p1"

PROFILE_SHA256 = "b363532884d1cae8049ab080d2b85a629f3b33a75f6621788d1e4c8f30737666"
PROFILE_CANDIDATE_SHA256 = (
    "15a121505c413da6c8c90a0ce21c44ebe853b2db5fa3f81f6735e9185fedc612"
)
PROFILE_APPROVAL_SHA256 = (
    "2831ce52802e7cbe4ec092431c71c18de05491da7ac8d48512014b1d43b3cb0c"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_profile_approval_record_still_binds_frozen_bytes() -> None:
    profile = P1 / "kv-recovery-profile.v0-draft.md"
    candidate = P1 / "kv-recovery-profile-approval-candidate.json"
    approval = P1 / "kv-recovery-profile-owner-approval.json"
    assert _sha256(profile) == PROFILE_SHA256
    assert _sha256(candidate) == PROFILE_CANDIDATE_SHA256
    assert _sha256(approval) == PROFILE_APPROVAL_SHA256

    record = _json(approval)
    approved = {artifact["role"]: artifact for artifact in record["approved_artifacts"]}
    assert approved["kv_recovery_profile"]["sha256"] == PROFILE_SHA256
    assert approved["approval_candidate"]["sha256"] == PROFILE_CANDIDATE_SHA256
    assert record["gate_effects"]["communication_mode_non_none_authorized"] is False


def test_mapping_approval_candidate_binds_current_mapping_bytes() -> None:
    mapping_path = P1 / "issue2-kv-recovery-mapping.v0-draft.md"
    mapping_sha = _sha256(mapping_path)
    approval = _json(P1 / "issue2-kv-recovery-mapping-approval-candidate.json")
    assert approval["proposed_artifact"]["sha256"] == mapping_sha
    assert approval["profile_owner_endorsement"]["approval_record_sha256"] == (
        PROFILE_APPROVAL_SHA256
    )
    assert (
        approval["gate_effects_before_approval"][
            "communication_mode_non_none_authorized"
        ]
        is False
    )

    mapping = mapping_path.read_text(encoding="utf-8")
    assert PROFILE_SHA256 in mapping
    assert PROFILE_APPROVAL_SHA256 in mapping


def test_overlay_binds_current_mapping_but_not_incomplete_config_normatively() -> None:
    mapping_sha = _sha256(P1 / "issue2-kv-recovery-mapping.v0-draft.md")
    config_sha = _sha256(P1 / "benchmark-134-fixed-8gib-config-candidate.json")
    overlay = (P1 / "kv-offload-base-mode-overlay.v0-draft.md").read_text(
        encoding="utf-8"
    )
    assert mapping_sha in overlay
    assert config_sha not in overlay
    assert "benchmark-134-fixed-8gib-config-candidate.json" in overlay
    assert "non-normative design input only" in overlay
    assert "p0_owner_review_required" in overlay
    assert "communication_mode=none" in overlay


def test_overlay_approval_candidate_binds_current_overlay_and_mapping() -> None:
    mapping_sha = _sha256(P1 / "issue2-kv-recovery-mapping.v0-draft.md")
    mapping_candidate_sha = _sha256(
        P1 / "issue2-kv-recovery-mapping-approval-candidate.json"
    )
    overlay_sha = _sha256(P1 / "kv-offload-base-mode-overlay.v0-draft.md")
    candidate = _json(P1 / "kv-offload-base-mode-overlay-approval-candidate.json")
    assert candidate["proposed_artifact"]["sha256"] == overlay_sha
    assert candidate["immutable_dependencies"]["issue2_mapping_sha256"] == (mapping_sha)
    assert (
        candidate["immutable_dependencies"]["issue2_mapping_approval_candidate_sha256"]
        == mapping_candidate_sha
    )
    assert (
        candidate["gate_effects_after_P0_approval_without_other_requirements"][
            "communication_mode_non_none_authorized"
        ]
        is False
    )


def test_config_candidate_binds_profile_owner_and_remains_non_runnable() -> None:
    config = _json(P1 / "benchmark-134-fixed-8gib-config-candidate.json")
    context = config["approved_context"]
    assert context["profile"]["sha256"] == PROFILE_SHA256
    assert context["profile_owner_approval_record"]["sha256"] == (
        PROFILE_APPROVAL_SHA256
    )
    assert config["runnability"]["is_runnable"] is False
    assert config["runnability"]["is_frozen_by_authority"] is False
    assert config["gate_effects"]["communication_mode_non_none_unblocked"] is False

    dependencies = config["formal_contract_dependencies"]
    assert dependencies["issue2_mapping"]["sha256"] == _sha256(
        P1 / "issue2-kv-recovery-mapping.v0-draft.md"
    )
    assert dependencies["issue2_mapping"]["approval_candidate_sha256"] == _sha256(
        P1 / "issue2-kv-recovery-mapping-approval-candidate.json"
    )
    assert dependencies["issue2_mapping"]["frozen_by_issue2_authority"] is False
    assert dependencies["p0_base_mode_overlay"]["sha256"] == _sha256(
        P1 / "kv-offload-base-mode-overlay.v0-draft.md"
    )
    assert dependencies["p0_base_mode_overlay"]["approval_candidate_sha256"] == _sha256(
        P1 / "kv-offload-base-mode-overlay-approval-candidate.json"
    )
    assert dependencies["p0_base_mode_overlay"]["frozen_by_P0_owner"] is False
    assert dependencies["complete_resolved_configuration"]["sha256"] is None
    assert dependencies["joint_admission_record"] is None


def test_cpu_result_binds_final_G0_candidate_and_probe_bytes() -> None:
    result = _json(P1 / "g0-pinned-pair-cpu-result.json")
    candidates = result["review_candidates"]
    assert candidates["issue2_mapping_sha256"] == _sha256(
        P1 / "issue2-kv-recovery-mapping.v0-draft.md"
    )
    assert candidates["issue2_mapping_approval_candidate_sha256"] == _sha256(
        P1 / "issue2-kv-recovery-mapping-approval-candidate.json"
    )
    assert candidates["P0_overlay_sha256"] == _sha256(
        P1 / "kv-offload-base-mode-overlay.v0-draft.md"
    )
    assert candidates["P0_overlay_approval_candidate_sha256"] == _sha256(
        P1 / "kv-offload-base-mode-overlay-approval-candidate.json"
    )
    assert candidates["incomplete_config_candidate_sha256"] == _sha256(
        P1 / "benchmark-134-fixed-8gib-config-candidate.json"
    )

    artifacts = result["probe_artifacts"]
    assert artifacts["script_sha256"] == _sha256(
        REPOSITORY_ROOT / "scripts" / "verify_g0_pinned_pair.py"
    )
    assert artifacts["probe_test_sha256"] == _sha256(
        REPOSITORY_ROOT / "tests" / "test_g0_pinned_pair_probe.py"
    )
    assert artifacts["config_test_sha256"] == _sha256(
        REPOSITORY_ROOT / "tests" / "test_g0_benchmark_134_config_candidate.py"
    )
    assert result["direct_cli_result"]["exit_code"] == 2
    assert result["direct_cli_result"]["overall_status"] == "BLOCKED"
    assert result["gate_effects"]["G0_complete"] is False
    assert result["gate_effects"]["NPU_authorized"] is False
