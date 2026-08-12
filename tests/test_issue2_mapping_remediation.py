from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
P1 = REPOSITORY_ROOT / "contracts" / "p1"

E3_PATH = P1 / "e3-stream-semantics-addendum.v0-draft.md"
POLICY_PATH = P1 / "kv-recovery-observer-policy.v0-draft.json"
POLICY_CANDIDATE_PATH = P1 / "kv-recovery-observer-policy-approval-candidate.json"
MAPPING_PATH = P1 / "issue2-kv-recovery-mapping.v0-draft.md"
MAPPING_CANDIDATE_PATH = P1 / "issue2-kv-recovery-mapping-approval-candidate.json"

V4_SHA256 = "8edb42b706b6cab14dfde2b109841cb8af090883c9ea86696ee779de21d0c9ed"
E3_SHA256 = "779faa2ef3f344c739d2092b7d4d250d0a4e3a4c5e76ec04ffcfa0d59ac8eddb"
POLICY_SHA256 = "fbee3bc4f74b8c5c20e929c4e37596b06b31c1b9cd02517d8461961a8aedf420"
POLICY_CANDIDATE_SHA256 = (
    "27cb52269fff8f10e376f3128384c4aac37f149ad685b89501f98ba50bc0cf29"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _collapsed(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def _review_item(candidate: dict[str, Any], item: int) -> dict[str, Any]:
    matches = [entry for entry in candidate["review_items"] if entry["item"] == item]
    assert len(matches) == 1
    return matches[0]


def _assert_all_false(values: dict[str, Any]) -> None:
    assert values
    assert all(value is False for value in values.values())


def test_remediated_artifact_digests_and_cross_references_are_exact() -> None:
    expected_digests = {
        E3_PATH: E3_SHA256,
        POLICY_PATH: POLICY_SHA256,
        POLICY_CANDIDATE_PATH: POLICY_CANDIDATE_SHA256,
    }
    for path, expected_digest in expected_digests.items():
        raw = path.read_bytes()
        assert raw.endswith(b"\n")
        assert b"\r\n" not in raw
        assert _sha256(path) == expected_digest

    for path in (MAPPING_PATH, MAPPING_CANDIDATE_PATH):
        raw = path.read_bytes()
        assert raw.endswith(b"\n")
        assert b"\r\n" not in raw
        assert len(_sha256(path)) == 64

    policy_candidate = _json(POLICY_CANDIDATE_PATH)
    assert policy_candidate["proposed_artifact"] == {
        "policy_id": "rlp.kv-recovery-observer-policy/v1alpha1",
        "path": POLICY_PATH.name,
        "sha256": POLICY_SHA256,
        "activation_effect": "none_without_all_later_gates",
    }

    mapping_candidate = _json(MAPPING_CANDIDATE_PATH)
    proposed_mapping = mapping_candidate["proposed_artifact"]
    assert proposed_mapping["path"] == MAPPING_PATH.name
    mapping_sha256 = _sha256(MAPPING_PATH)
    assert proposed_mapping["sha256"] == mapping_sha256
    assert mapping_sha256 in mapping_candidate["approval_statement_template"]
    assert _sha256(MAPPING_CANDIDATE_PATH) not in MAPPING_CANDIDATE_PATH.read_text(
        encoding="utf-8"
    )
    item4b = mapping_candidate["item4B_activation_prerequisite"]
    assert item4b["path"] == POLICY_PATH.name
    assert item4b["sha256"] == POLICY_SHA256
    assert item4b["approval_candidate_path"] == POLICY_CANDIDATE_PATH.name
    assert item4b["approval_candidate_sha256"] == POLICY_CANDIDATE_SHA256
    assert _collapsed(MAPPING_PATH).count(POLICY_SHA256) == 1


def test_v4_3_e3_split_and_point_sentinel_intersection_fails_closed() -> None:
    mapping_candidate = _json(MAPPING_CANDIDATE_PATH)
    dependencies = mapping_candidate["immutable_semantic_dependencies"]
    v4 = dependencies["idle_evidence_contract_v4_3"]
    e3 = dependencies["e3_stream_semantics_addendum"]
    assert v4["sha256"] == V4_SHA256
    assert e3 == {"path": E3_PATH.name, "sha256": E3_SHA256}
    assert v4["sha256"] != e3["sha256"]
    assert v4["path"] != e3["path"]

    e3_text = E3_PATH.read_text(encoding="utf-8")
    e3_collapsed = " ".join(e3_text.split())
    mapping_collapsed = _collapsed(MAPPING_PATH)
    assert V4_SHA256 in e3_text
    assert E3_SHA256 not in e3_text  # The addendum cannot self-hash.
    assert "does not edit, replace, or silently extend" in e3_collapsed
    assert V4_SHA256 in mapping_collapsed
    assert E3_SHA256 in mapping_collapsed
    assert "independent post-v4.3 dependency" in mapping_collapsed

    intersection_rows = [
        line
        for line in e3_text.splitlines()
        if line.startswith("| Zero duration, legal point role, stream `0xFFFFFFFF` |")
    ]
    assert len(intersection_rows) == 1
    cells = [cell.strip() for cell in intersection_rows[0].strip("|").split("|")]
    assert cells == [
        "Zero duration, legal point role, stream `0xFFFFFFFF`",
        "`zero_duration_point_event_ignored` plus unassigned-stream lineage",
        "No status change",
        "None",
        "None",
        "Set false",
    ]
    assert (
        "a legal zero-duration point carrying `0xFFFFFFFF` remains point-only"
        in e3_collapsed
    )
    assert "both the point-only rules in Section 6.1 and this completeness" in (
        e3_collapsed
    )
    assert (
        "`observed_universe_scan_complete=false` for one device forbids an "
        "absence claim"
    ) in e3_collapsed
    assert "a legal point with stream `0xFFFFFFFF`" in e3_collapsed
    assert "audited PR #15 bytes are **not yet conformant**" in e3_collapsed
    assert "Before activation, the implementation must change" in e3_collapsed

    item7 = _review_item(mapping_candidate, 7)["decision"]
    assert "two independent semantic dependencies" in item7
    assert "SHA-bound Idle Evidence Contract v4.3" in item7
    assert "separately SHA-bound E3 addendum" in item7
    assert "sentinel-plus-point intersection" in item7
    assert "PR #15 does not yet conform" in item7
    assert "completeness, duplicate suppression, and fail-closed behavior" in item7


def test_item_4a_and_4b_authorities_are_disjoint() -> None:
    mapping_candidate = _json(MAPPING_CANDIDATE_PATH)
    item4 = _review_item(mapping_candidate, 4)
    assert item4["status"] == "pending_authority_split"
    subitems = {entry["item"]: entry for entry in item4["subitems"]}
    assert set(subitems) == {"4A", "4B"}

    item4a = subitems["4A"]
    assert item4a["authority_scope"] == "issue2"
    assert item4a["status"] == "pending"
    assert "one H2D span and three explicit edges" in item4a["decision"]
    assert "concrete worker and EngineCore edge emitters" in item4a["decision"]

    item4b = subitems["4B"]
    assert item4b["authority_scope"] == (
        "recovery_profile_P0_and_runtime_owners_plus_later_joint_admission"
    )
    assert item4b["status"] == "external_authority_ratification_required"
    assert item4b["issue2_approval_effect"] == (
        "activation_prerequisite_acknowledgement_only"
    )
    assert item4b["policy_sha256"] == POLICY_SHA256
    assert "Issue-2 authority does not approve those details" in item4b["decision"]

    policy = _json(POLICY_PATH)
    boundary = policy["authority_boundary"]
    assert boundary["issue2_authority_may_approve_this_policy"] is False
    assert boundary["issue2_mapping_may_list_this_policy_as_an_activation_prerequisite"]
    assert set(boundary["required_policy_authorities"]) == {
        "recovery_profile_owner",
        "P0_base_mode_owner",
        "runtime_observer_implementation_owner",
    }

    policy_candidate = _json(POLICY_CANDIDATE_PATH)
    split = policy_candidate["authority_split"]
    assert split["profile_and_P0_owner"]["items"] == [1, 2, 3, 4, 5]
    assert split["runtime_observer_implementation_owner"]["items"] == [6, 7, 8]
    assert split["issue2_authority_may_substitute"] is False
    joint_may_substitute = split[
        "joint_admission_may_substitute_for_missing_policy_owner_approval"
    ]
    assert joint_may_substitute is False


def test_three_h2d_edges_have_explicit_id_handoffs_and_concrete_emitters() -> None:
    mapping = MAPPING_PATH.read_text(encoding="utf-8")
    collapsed = " ".join(mapping.split())
    edges = [
        "preempted(e) -> communication_started(e+1)",
        "communication_started(e+1) -> communication_done(e+1)",
        "communication_done(e+1) -> admission_started(e+1)",
    ]
    for edge in edges:
        assert mapping.count(edge) == 1

    assert "`base_preempted_event_id`" in mapping
    assert "`communication_started_event_id`" in mapping
    assert "`communication_done_event_id`" in mapping
    assert "both endpoint event IDs are explicitly known" in collapsed
    assert "rank-0 worker issue-2 adapter emits it in the worker shard" in collapsed
    assert "same worker adapter emits it" in collapsed
    assert (
        "EngineCore- side issue-2 adapter emits it in the EngineCore shard" in collapsed
    )
    assert "never creates, selects, repairs, or deduplicates" in collapsed
    assert "timestamp or file order" in collapsed

    policy = _json(POLICY_PATH)
    pending_fields = set(policy["pending_context_policy"]["required_fields"])
    assert {
        "base_preempted_event_id",
        "communication_started_event_id",
        "transfer_id",
        "connector_job_id",
        "block_set_id",
    } <= pending_fields
    scheduler_sidecar = set(
        policy["sidecar_and_receipt_policy"]["scheduler_to_worker_sidecar"]
    )
    worker_receipt = set(
        policy["sidecar_and_receipt_policy"][
            "worker_to_scheduler_or_engine_core_receipt"
        ]
    )
    assert "base_preempted_event_id" in scheduler_sidecar
    assert "communication_done_event_id" in worker_receipt
    assert (
        policy["edge_emitter_prerequisite"][
            "current_default_off_WIP_complete_for_all_three_emitters"
        ]
        is False
    )


def test_capacity_and_loss_reason_are_owned_only_by_item_4b_policy() -> None:
    policy = _json(POLICY_PATH)
    capacity = policy["capacity_policy"]
    assert capacity["name"] == "observer_transfer_capacity_bundle"
    assert capacity["candidate_values"] == {
        "max_prepared_transfer_attempts_per_process": 4096,
        "max_pending_h2d_contexts_per_process": 4096,
        "max_pending_d2h_contexts_per_process": 4096,
        "max_h2d_receipts_per_worker_step": 4096,
    }
    assert capacity["frozen_by_this_unapproved_candidate"] is False
    constants = capacity["source_chain"]["runtime_constants"]
    assert {constant["symbol"] for constant in constants} == {
        "MAX_PENDING_H2D_CONTEXTS_PER_PROCESS",
        "MAX_H2D_RECEIPTS_PER_WORKER_STEP",
    }
    assert {constant["value"] for constant in constants} == {4096}

    failure = policy["capacity_failure_policy"]
    assert failure["proposed_loss_reason"] == "serialization_failure"
    assert failure["serving_failure_policy"] == "fail_open"
    assert failure["formal_evidence_failure_policy"] == "fail_closed"
    assert set(failure["applies_to"]) == {
        "prepared_transfer_attempt_capacity_exhaustion",
        "pending_h2d_context_capacity_exhaustion",
        "pending_d2h_context_capacity_exhaustion",
        "h2d_receipt_append_or_aggregation_capacity_exhaustion",
    }
    pre_start = failure["pre_start_or_pending_context_capacity_behavior"]
    assert "emit_no_corresponding_new_base_communication_event_pair_or_edge" in (
        pre_start
    )
    late_receipt = failure["late_receipt_capacity_behavior"]
    assert (
        "retain_every_already_written_event_edge_and_profile_record_without_"
        "retraction_rewrite_or_duplicate"
    ) in late_receipt
    assert (
        "emit_no_worker_to_EngineCore_receipt_and_no_third_communication_done_to_"
        "admission_started_edge"
    ) in late_receipt
    assert "emit_no_corresponding_base_communication_pair_or_edge" not in (
        POLICY_PATH.read_text(encoding="utf-8")
    )
    ratification = failure["profile_owner_digest_ratification"]
    assert ratification["required"] is True
    assert ratification["ratified"] is False
    assert ratification["record_path"] is None
    assert ratification["record_sha256"] is None

    policy_candidate = _json(POLICY_CANDIDATE_PATH)
    assert "4096" in _review_item(policy_candidate, 2)["decision"]
    assert "serialization_failure" in _review_item(policy_candidate, 3)["decision"]

    mapping = MAPPING_PATH.read_text(encoding="utf-8")
    mapping_collapsed = " ".join(mapping.split())
    mapping_candidate_raw = MAPPING_CANDIDATE_PATH.read_text(encoding="utf-8")
    assert mapping.count("4096") == 1
    assert mapping.count("serialization_failure") == 1
    assert (
        "This mapping does not itself freeze "
        "`max_pending_h2d_contexts_per_process=4096` or assign "
        "`serialization_failure`"
    ) in mapping_collapsed
    assert "Receipt append/aggregation exhaustion is a later failure" in (mapping)
    assert "emits no receipt and no third done-to-admission edge" in mapping_collapsed
    assert "retains every record already written" in mapping_collapsed
    assert "4096" not in mapping_candidate_raw
    assert "serialization_failure" not in mapping_candidate_raw


def test_every_current_activation_and_authorization_gate_remains_false() -> None:
    policy = _json(POLICY_PATH)
    _assert_all_false(policy["activation_prerequisites"])

    policy_candidate = _json(POLICY_CANDIDATE_PATH)
    _assert_all_false(policy_candidate["gate_effects"])
    assert all(item["status"] == "pending" for item in policy_candidate["review_items"])

    mapping_candidate = _json(MAPPING_CANDIDATE_PATH)
    _assert_all_false(mapping_candidate["gate_effects_before_approval"])

    hypothetical = dict(
        mapping_candidate[
            "gate_effects_after_issue2_approval_without_other_requirements"
        ]
    )
    # Semantic mapping freeze is the sole hypothetical change; it is not an
    # activation or execution gate and does not authorize any runtime action.
    assert hypothetical.pop("mapping_frozen") is True
    _assert_all_false(hypothetical)

    prerequisite = mapping_candidate["item4B_activation_prerequisite"]
    assert prerequisite["issue2_authority_approves_policy_contents"] is False
    assert mapping_candidate["candidate_effect"].startswith("none_until_")
    assert policy_candidate["candidate_effect"].startswith("none_until_")
