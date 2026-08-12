from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
P1 = REPOSITORY_ROOT / "contracts" / "p1"

POLICY = P1 / "kv-recovery-observer-policy.v0-draft.json"
POLICY_CANDIDATE = P1 / "kv-recovery-observer-policy-approval-candidate.json"
POLICY_APPROVAL = P1 / "kv-recovery-observer-policy-profile-p0-owner-approval.json"
OVERLAY = P1 / "kv-offload-base-mode-overlay.v0-draft.md"
OVERLAY_CANDIDATE = P1 / "kv-offload-base-mode-overlay-approval-candidate.json"
OVERLAY_RATIFICATION_CANDIDATE = (
    P1 / "kv-offload-base-mode-overlay-owner-ratification-candidate.r2.json"
)
OVERLAY_RATIFICATION = P1 / "kv-offload-base-mode-overlay-owner-ratification.r2.json"
G0_RESULT = P1 / "g0-mapping-remediation-cpu-result.json"
G1_CANDIDATE = P1 / "g1-cpu-wiring-reauthorization-candidate.r2.json"
G1_REAUTHORIZATION = P1 / "g1-cpu-wiring-owner-reauthorization.r2.json"

POLICY_SHA256 = "fbee3bc4f74b8c5c20e929c4e37596b06b31c1b9cd02517d8461961a8aedf420"
POLICY_CANDIDATE_SHA256 = (
    "27cb52269fff8f10e376f3128384c4aac37f149ad685b89501f98ba50bc0cf29"
)
OVERLAY_SHA256 = "d80771b793a9513cdbd4fc2001e21771c56a59d49340ee88d4381027d70b1d5a"
OVERLAY_CANDIDATE_SHA256 = (
    "de889357af659d8e9c1f7daf0aa32656761e80dcf0fea29ef60809912f513694"
)
OVERLAY_RATIFICATION_CANDIDATE_SHA256 = (
    "ffcdc6ce770906aa98675f630f07caf5c719485ef8f0afbfc4d3e94ae8e87e9a"
)
G0_RESULT_SHA256 = "4b378d10cef6be10fa3fb5a840402da77b1da755781118127a5d30b1cc4b7eb2"
G1_CANDIDATE_SHA256 = "a0fbcc863181558fda3d8c82be62dfce4a9594ea1802f053979cae99900597b5"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _assert_all_false(values: dict[str, Any], *, except_for: set[str]) -> None:
    assert set(values) >= except_for
    for key, value in values.items():
        if key not in except_for:
            assert value is False, key


def test_profile_P0_owner_approval_binds_exact_policy_and_only_items_1_5() -> None:
    assert _sha256(POLICY) == POLICY_SHA256
    assert _sha256(POLICY_CANDIDATE) == POLICY_CANDIDATE_SHA256

    candidate = _json(POLICY_CANDIDATE)
    approval = _json(POLICY_APPROVAL)
    artifacts = {item["role"]: item for item in approval["approved_artifacts"]}
    assert artifacts["Item4B_observer_policy"]["sha256"] == _sha256(POLICY)
    assert artifacts["Item4B_approval_candidate"]["sha256"] == _sha256(POLICY_CANDIDATE)

    expected_statement = candidate[
        "profile_P0_owner_approval_statement_template"
    ].replace("<FINAL_POLICY_APPROVAL_CANDIDATE_SHA256>", POLICY_CANDIDATE_SHA256)
    assert approval["approval_source"]["statement"] == expected_statement
    assert approval["accepted_decisions"]["accepted_items"] == [1, 2, 3, 4, 5]
    assert approval["accepted_decisions"][
        "runtime_observer_implementation_owner_items"
    ] == [6, 7, 8]
    assert (
        approval["accepted_decisions"][
            "runtime_observer_implementation_owner_items_approved"
        ]
        is False
    )
    assert approval["separate_pending_authority"]["owner"] is None
    assert approval["separate_pending_authority"]["approval_record"] is None

    capacities = approval["approved_policy_interpretation"]["candidate_capacities"]
    assert set(capacities.values()) == {4096}
    gates = approval["gate_effects"]
    assert gates["Item4B_profile_P0_owner_items_approved"] is True
    _assert_all_false(gates, except_for={"Item4B_profile_P0_owner_items_approved"})


def test_overlay_ratification_binds_exact_items_but_not_independent_authorities() -> (
    None
):
    assert _sha256(OVERLAY) == OVERLAY_SHA256
    assert _sha256(OVERLAY_CANDIDATE) == OVERLAY_CANDIDATE_SHA256
    assert _sha256(OVERLAY_RATIFICATION_CANDIDATE) == (
        OVERLAY_RATIFICATION_CANDIDATE_SHA256
    )

    candidate = _json(OVERLAY_RATIFICATION_CANDIDATE)
    ratification = _json(OVERLAY_RATIFICATION)
    artifacts = {item["role"]: item for item in ratification["approved_artifacts"]}
    assert artifacts["P0_base_mode_overlay"]["sha256"] == _sha256(OVERLAY)
    assert artifacts["overlay_approval_candidate"]["sha256"] == _sha256(
        OVERLAY_CANDIDATE
    )
    assert (
        ratification["approval_source"]["statement"]
        == candidate["required_exact_owner_statement"]
    )
    assert ratification["accepted_decisions"]["accepted_items"] == list(range(1, 9))

    context = ratification["ratification_candidate_context"]
    assert context["sha256"] == _sha256(OVERLAY_RATIFICATION_CANDIDATE)
    assert context["approved_as_an_additional_artifact_by_the_owner_statement"] is False
    policy_approval = ratification["recognized_Item4B_profile_P0_approval"]
    assert policy_approval["sha256"] == _sha256(POLICY_APPROVAL)
    assert policy_approval["runtime_owner_items_6_8_approved"] is False

    requirements = ratification["independent_requirements"]
    assert requirements["issue2_mapping_authority_approval_record"] is None
    assert requirements["Item4B_runtime_owner_approval_record"] is None
    assert requirements["complete_configuration_authority_approval_record"] is None
    assert requirements["joint_admission_record"] is None
    gates = ratification["gate_effects"]
    assert gates["P0_overlay_frozen"] is True
    assert gates["Item4B_profile_P0_owner_items_approved"] is True
    _assert_all_false(
        gates,
        except_for={"P0_overlay_frozen", "Item4B_profile_P0_owner_items_approved"},
    )


def test_G1_reauthorization_binds_current_chain_and_only_opens_CPU_source_work() -> (
    None
):
    assert _sha256(G0_RESULT) == G0_RESULT_SHA256
    assert _sha256(G1_CANDIDATE) == G1_CANDIDATE_SHA256

    candidate = _json(G1_CANDIDATE)
    authorization = _json(G1_REAUTHORIZATION)
    assert (
        authorization["authorization_source"]["statement"]
        == candidate["required_exact_owner_statement"]
    )
    artifacts = authorization["authorized_artifacts"]
    assert artifacts["reauthorization_candidate"]["sha256"] == _sha256(G1_CANDIDATE)
    assert artifacts["G0_remediation_CPU_result"]["sha256"] == _sha256(G0_RESULT)
    assert artifacts["Item4B_profile_P0_owner_approval"]["sha256"] == _sha256(
        POLICY_APPROVAL
    )
    assert artifacts["P0_overlay_owner_approval"]["sha256"] == _sha256(
        OVERLAY_RATIFICATION
    )

    chain = authorization["current_candidate_chain"]
    candidate_chain = candidate["current_authority_chain"]
    for key in (
        "recovery_profile_sha256",
        "profile_owner_approval_record_sha256",
        "E3_addendum_sha256",
        "Item4B_policy_sha256",
        "Item4B_approval_candidate_sha256",
        "issue2_mapping_candidate_sha256",
        "issue2_mapping_approval_candidate_sha256",
        "P0_overlay_sha256",
        "P0_overlay_approval_candidate_sha256",
    ):
        assert chain[key] == candidate_chain[key]
    assert chain["issue2_mapping_authority_approval_record"] is None
    assert authorization["repository_context"]["profiler_G0_published_commit"] is None

    constraints = authorization["implementation_constraints"]
    assert constraints["default_enabled"] is False
    assert constraints["communication_mode_while_activation_blocked"] == "none"
    assert constraints["serving_failure_policy"] == "fail_open"
    assert constraints["formal_evidence_failure_policy"] == "fail_closed"
    gates = authorization["gate_effects_by_this_record"]
    source_gate = "G1_CPU_side_source_work_reauthorized_for_current_digests"
    assert gates[source_gate] is True
    _assert_all_false(gates, except_for={source_gate})


def test_historical_records_remain_immutable_and_superseded() -> None:
    historical_overlay = P1 / "kv-offload-base-mode-overlay-owner-approval.json"
    historical_G1 = P1 / "g1-cpu-wiring-owner-authorization.json"
    assert _sha256(historical_overlay) == (
        "c17dad09ab005c839ad5cd52c0d65cb0c7ad9064ad9431deed10e8b7a99aa782"
    )
    assert _sha256(historical_G1) == (
        "82386d4328463c8d7c32ad572f429a350af42bb04f8dda552e049788b88c6ecd"
    )

    ratification = _json(OVERLAY_RATIFICATION)
    assert ratification["historical_pending_record"]["sha256"] == _sha256(
        historical_overlay
    )
    authorization = _json(G1_REAUTHORIZATION)
    assert authorization["superseded_authorization"]["sha256"] == _sha256(historical_G1)
    assert (
        authorization["superseded_authorization"]["authorizes_current_digest_work"]
        is False
    )


def test_new_records_are_downstream_leaf_records_with_stable_encoding() -> None:
    for path in (POLICY_APPROVAL, OVERLAY_RATIFICATION, G1_REAUTHORIZATION):
        raw = path.read_bytes()
        assert raw.endswith(b"\n")
        assert b"\r\n" not in raw
        assert _sha256(path) not in path.read_text(encoding="utf-8")

    assert POLICY_APPROVAL.name in OVERLAY_RATIFICATION.read_text(encoding="utf-8")
    assert OVERLAY_RATIFICATION.name in G1_REAUTHORIZATION.read_text(encoding="utf-8")
    assert G1_REAUTHORIZATION.name not in POLICY_APPROVAL.read_text(encoding="utf-8")
    assert G1_REAUTHORIZATION.name not in OVERLAY_RATIFICATION.read_text(
        encoding="utf-8"
    )
