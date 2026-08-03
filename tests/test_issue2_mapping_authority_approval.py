from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
P1 = REPOSITORY_ROOT / "contracts" / "p1"

MAPPING = P1 / "issue2-kv-recovery-mapping.v0-draft.md"
MAPPING_CANDIDATE = P1 / "issue2-kv-recovery-mapping-approval-candidate.json"
MAPPING_APPROVAL = P1 / "issue2-kv-recovery-mapping-authority-approval.json"
POLICY = P1 / "kv-recovery-observer-policy.v0-draft.json"
POLICY_APPROVAL = P1 / "kv-recovery-observer-policy-profile-p0-owner-approval.json"
OVERLAY_APPROVAL = P1 / "kv-offload-base-mode-overlay-owner-ratification.r2.json"

MAPPING_SHA256 = "095944bbbb1a3ad3518aebfdd61c820ade3affdebd6024b47389cdaec24a3fa3"
MAPPING_CANDIDATE_SHA256 = (
    "a686243ffd9c650790e6421e5f976a2a5c010a5d2480e7a30ad8722a9218f3f7"
)
POLICY_SHA256 = "fbee3bc4f74b8c5c20e929c4e37596b06b31c1b9cd02517d8461961a8aedf420"
POLICY_APPROVAL_SHA256 = (
    "322df19ade75797fc4c3f43fe96e689404ef60a270c92081afea03683e734c91"
)
OVERLAY_APPROVAL_SHA256 = (
    "50d7deb8f98fcdca36303297a4ce6f7958ae619574d2e1994872936b6fc583a3"
)
COMMENT_BODY_SHA256 = "c868775cbbe70b2f3979224224c6f1f57bfc4de41c532542f81d0342e39d0839"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_authority_record_binds_exact_comment_mapping_and_candidate() -> None:
    assert _sha256(MAPPING) == MAPPING_SHA256
    assert _sha256(MAPPING_CANDIDATE) == MAPPING_CANDIDATE_SHA256

    candidate = _json(MAPPING_CANDIDATE)
    approval = _json(MAPPING_APPROVAL)
    source = approval["approval_source"]
    expected_statement = candidate["approval_statement_template"].replace(
        "<FINAL_APPROVAL_CANDIDATE_SHA256>", MAPPING_CANDIDATE_SHA256
    )
    assert source["statement"] == f"同学你好，{expected_statement}"
    assert source["comment_id"] == 5166814016
    assert source["responds_to_rereview_request_comment_id"] == 5166683340
    assert source["author"] == approval["authority"] == "Luqhhh"
    assert source["author_association"] == "MEMBER"
    assert source["created_at"] == source["updated_at"] == approval["recorded_at"]
    exact_api_body = source["statement"] + "\n" * source["api_body_trailing_lf_count"]
    assert hashlib.sha256(exact_api_body.encode()).hexdigest() == COMMENT_BODY_SHA256
    assert source["api_body_sha256"] == COMMENT_BODY_SHA256

    artifacts = {item["role"]: item for item in approval["approved_artifacts"]}
    assert artifacts["issue2_specialty_mapping"]["sha256"] == _sha256(MAPPING)
    assert artifacts["issue2_mapping_approval_candidate"]["sha256"] == _sha256(
        MAPPING_CANDIDATE
    )
    assert approval["accepted_decisions"]["accepted_items"] == [
        1,
        2,
        3,
        "4A",
        5,
        6,
        7,
        8,
    ]
    assert approval["accepted_decisions"]["excluded_items"] == ["4B"]


def test_authority_record_freezes_exact_asymmetric_mapping_semantics() -> None:
    approval = _json(MAPPING_APPROVAL)
    semantics = approval["approved_mapping_semantics"]
    assert semantics["active_P0_evidence_code"] == (
        "issue2:kv-recovery-v1alpha1:h2d_restore"
    )
    assert semantics["h2d_restore"] == {
        "base_span_count": 1,
        "explicit_base_edge_count": 3,
        "timestamp_inference_allowed": False,
    }
    for operation in ("d2h_preserve", "transfer_wait"):
        assert semantics[operation] == {
            "base_span_count": 0,
            "base_edge_count": 0,
            "profile_evidence_only": True,
        }
    assert semantics["E3_sentinel_plus_point_intersection"] == "accepted_fail_closed"
    assert semantics["audited_PR_15_conformance"] == (
        "KNOWN_GAP_ACCEPTED_AS_GAP_NOT_WAIVED"
    )
    assert semantics["mapping_conformance_required_before_activation"] is True

    boundary = approval["authority_boundary"]
    assert boundary["Item4A_mapping_approved"] is True
    assert boundary["Item4B_policy_sha256"] == _sha256(POLICY) == POLICY_SHA256
    assert boundary["Item4B_acknowledged_only_as_activation_prerequisite"] is True
    assert boundary["Item4B_approved_by_this_record"] is False
    assert boundary["P0_overlay_approved_by_this_record"] is False


def test_independent_records_remain_separate_and_activation_stays_closed() -> None:
    approval = _json(MAPPING_APPROVAL)
    context = approval["observed_independent_context_not_approved_by_this_comment"]
    policy_approval = context["Item4B_profile_P0_owner_approval"]
    assert _sha256(POLICY_APPROVAL) == POLICY_APPROVAL_SHA256
    assert policy_approval["sha256"] == _sha256(POLICY_APPROVAL)
    assert policy_approval["approved_items"] == [1, 2, 3, 4, 5]
    assert (
        context["Item4B_runtime_implementation_owner_items_6_8_approval_record"] is None
    )
    assert _sha256(OVERLAY_APPROVAL) == OVERLAY_APPROVAL_SHA256
    assert context["P0_overlay_owner_approval"]["sha256"] == _sha256(OVERLAY_APPROVAL)
    for key in (
        "complete_configuration_authority_approval_record",
        "runtime_conformance_record",
        "joint_admission_record",
        "runtime_activation_record",
    ):
        assert context[key] is None

    gates = approval["gate_effects_by_this_record"]
    assert gates["issue2_mapping_frozen"] is True
    assert all(
        value is False
        for name, value in gates.items()
        if name != "issue2_mapping_frozen"
    )


def test_authority_record_is_a_downstream_leaf_with_stable_encoding() -> None:
    raw = MAPPING_APPROVAL.read_bytes()
    assert raw.endswith(b"\n")
    assert b"\r\n" not in raw
    assert _sha256(MAPPING_APPROVAL) not in MAPPING_APPROVAL.read_text(encoding="utf-8")
    assert MAPPING_APPROVAL.name not in MAPPING.read_text(encoding="utf-8")
    assert MAPPING_APPROVAL.name not in MAPPING_CANDIDATE.read_text(encoding="utf-8")

    candidate = _json(MAPPING_CANDIDATE)
    assert [item["status"] for item in candidate["review_items"][:3]] == [
        "pending",
        "pending",
        "pending",
    ]
    item4 = next(item for item in candidate["review_items"] if item["item"] == 4)
    assert item4["status"] == "pending_authority_split"
    assert {entry["item"]: entry["status"] for entry in item4["subitems"]} == {
        "4A": "pending",
        "4B": "external_authority_ratification_required",
    }
