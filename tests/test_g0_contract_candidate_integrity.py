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
HISTORICAL_MAPPING_SHA256 = (
    "dca914f989f3a98d43fb9fa2538f7c43a375e8f22f5deb7e09343aee5ee7bc19"
)
HISTORICAL_MAPPING_CANDIDATE_SHA256 = (
    "f3cfdd6d9463251fdc27e01164d9f33a1efcc6c155f6d51959e0e1989d23a350"
)
HISTORICAL_OVERLAY_SHA256 = (
    "6e035c29664038cdc93b545538cee6fc31abfb79e455d994851f8c9dbfd1c734"
)
HISTORICAL_OVERLAY_CANDIDATE_SHA256 = (
    "169c1923ed2d37fe0ea5f88d05bcc9e35424742bb53892408ac5059485609cb5"
)
HISTORICAL_CONFIG_SHA256 = (
    "b57fed50aa067e937728fe6f618a37246c50becd5ac94bd8eef3bc2ee7184b3a"
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
    config_sha = _sha256(P1 / "benchmark-134-fixed-8gib-config-candidate.r2.json")
    overlay = (P1 / "kv-offload-base-mode-overlay.v0-draft.md").read_text(
        encoding="utf-8"
    )
    assert mapping_sha in overlay
    assert config_sha not in overlay
    assert "benchmark-134-fixed-8gib-config-candidate.r2.json" in overlay
    assert "non-normative design input only" in overlay
    assert "p0_owner_rereview_required" in overlay
    assert "communication_mode=none" in overlay


def test_overlay_approval_candidate_binds_current_overlay_and_mapping() -> None:
    mapping_sha = _sha256(P1 / "issue2-kv-recovery-mapping.v0-draft.md")
    mapping_candidate_sha = _sha256(
        P1 / "issue2-kv-recovery-mapping-approval-candidate.json"
    )
    overlay_sha = _sha256(P1 / "kv-offload-base-mode-overlay.v0-draft.md")
    candidate = _json(P1 / "kv-offload-base-mode-overlay-approval-candidate.json")
    assert candidate["proposed_artifact"]["sha256"] == overlay_sha
    assert candidate["separate_authority_prerequisites"]["issue2_mapping"][
        "sha256"
    ] == (mapping_sha)
    assert (
        candidate["separate_authority_prerequisites"]["issue2_mapping"][
            "approval_candidate_sha256"
        ]
        == mapping_candidate_sha
    )
    assert (
        candidate["gate_effects_after_P0_approval_without_other_requirements"][
            "communication_mode_non_none_authorized"
        ]
        is False
    )


def test_config_candidate_binds_profile_owner_and_remains_non_runnable() -> None:
    config = _json(P1 / "benchmark-134-fixed-8gib-config-candidate.r2.json")
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
    assert dependencies["item4B_observer_policy"]["sha256"] == _sha256(
        P1 / "kv-recovery-observer-policy.v0-draft.json"
    )
    assert dependencies["item4B_observer_policy"]["fully_ratified"] is False
    assert dependencies["idle_evidence_semantics"]["e3_addendum_sha256"] == (
        _sha256(P1 / "e3-stream-semantics-addendum.v0-draft.md")
    )
    assert dependencies["complete_resolved_configuration"]["sha256"] is None
    assert dependencies["joint_admission_record"] is None


def test_pre_remediation_cpu_result_remains_immutable_historical_evidence() -> None:
    result = _json(P1 / "g0-pinned-pair-cpu-result.json")
    candidates = result["review_candidates"]
    assert candidates["issue2_mapping_sha256"] == HISTORICAL_MAPPING_SHA256
    assert candidates["issue2_mapping_approval_candidate_sha256"] == (
        HISTORICAL_MAPPING_CANDIDATE_SHA256
    )
    assert candidates["P0_overlay_sha256"] == HISTORICAL_OVERLAY_SHA256
    assert candidates["P0_overlay_approval_candidate_sha256"] == (
        HISTORICAL_OVERLAY_CANDIDATE_SHA256
    )
    assert candidates["incomplete_config_candidate_sha256"] == _sha256(
        P1 / "benchmark-134-fixed-8gib-config-candidate.json"
    )
    assert candidates["incomplete_config_candidate_sha256"] == HISTORICAL_CONFIG_SHA256

    artifacts = result["probe_artifacts"]
    assert artifacts["script_sha256"] == (
        "3e5c666f63969f523f8f70c07ed8c5141706887b11a775c757b4dc12cf69df3f"
    )
    assert artifacts["probe_test_sha256"] == (
        "4ad8e5162f0c91f3fcd188a78ba602dd576d97c322cd8f596d545c674f6ace4f"
    )
    assert artifacts["config_test_sha256"] == (
        "5b4823a90e022b4463d2f2899f9aae522bbb62185826d7ee1b8fa55604372e85"
    )
    assert result["direct_cli_result"]["exit_code"] == 2
    assert result["direct_cli_result"]["overall_status"] == "BLOCKED"
    assert result["gate_effects"]["G0_complete"] is False
    assert result["gate_effects"]["NPU_authorized"] is False


def test_current_overlay_ratification_candidate_freezes_nothing() -> None:
    record = _json(
        P1 / "kv-offload-base-mode-overlay-owner-ratification-candidate.r2.json"
    )
    assert record["proposed_artifacts"]["overlay"]["sha256"] == _sha256(
        P1 / "kv-offload-base-mode-overlay.v0-draft.md"
    )
    assert record["proposed_artifacts"]["approval_candidate"]["sha256"] == (
        _sha256(P1 / "kv-offload-base-mode-overlay-approval-candidate.json")
    )
    assert record["candidate_effect"] == "none"
    assert record["gate_effects"]["P0_overlay_frozen"] is False
    assert record["gate_effects"]["G1_runtime_activation_authorized"] is False
