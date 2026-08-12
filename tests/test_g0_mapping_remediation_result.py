from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
P1 = REPOSITORY_ROOT / "contracts" / "p1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _canonical_sha256(path: Path) -> str:
    payload = _json(path)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def test_remediation_result_binds_current_candidate_chain() -> None:
    result = _json(P1 / "g0-mapping-remediation-cpu-result.json")
    current = result["current_candidates"]

    expected = {
        "E3_addendum_sha256": "e3-stream-semantics-addendum.v0-draft.md",
        "Item4B_policy_sha256": "kv-recovery-observer-policy.v0-draft.json",
        "Item4B_approval_candidate_sha256": (
            "kv-recovery-observer-policy-approval-candidate.json"
        ),
        "issue2_mapping_sha256": "issue2-kv-recovery-mapping.v0-draft.md",
        "issue2_mapping_approval_candidate_sha256": (
            "issue2-kv-recovery-mapping-approval-candidate.json"
        ),
        "P0_overlay_sha256": "kv-offload-base-mode-overlay.v0-draft.md",
        "P0_overlay_approval_candidate_sha256": (
            "kv-offload-base-mode-overlay-approval-candidate.json"
        ),
        "P0_overlay_ratification_candidate_sha256": (
            "kv-offload-base-mode-overlay-owner-ratification-candidate.r2.json"
        ),
    }
    for field, filename in expected.items():
        assert current[field] == _sha256(P1 / filename)

    config = P1 / "benchmark-134-fixed-8gib-config-candidate.r2.json"
    assert current["incomplete_config_r2_raw_sha256"] == _sha256(config)
    assert current["incomplete_config_r2_canonical_sha256"] == _canonical_sha256(config)


def test_historical_result_is_preserved_but_not_current_authority() -> None:
    result = _json(P1 / "g0-mapping-remediation-cpu-result.json")
    historical = result["historical_evidence_preserved"]
    assert historical["sha256"] == _sha256(P1 / "g0-pinned-pair-cpu-result.json")
    assert historical["modified"] is False
    assert historical["still_authorizes_current_mapping_or_overlay"] is False


def test_CPU_pass_does_not_open_any_activation_gate() -> None:
    result = _json(P1 / "g0-mapping-remediation-cpu-result.json")
    gates = result["gate_effects"]
    assert gates["G0_remediation_candidate_integrity_passed"] is True
    for gate in (
        "issue2_mapping_frozen",
        "Item4B_policy_profile_P0_owner_ratified",
        "Item4B_policy_runtime_owner_ratified",
        "P0_overlay_frozen",
        "complete_configuration_frozen",
        "joint_admission_present",
        "G0_complete",
        "communication_mode_non_none_authorized",
        "G1_runtime_wiring_reauthorized_for_current_digests",
        "G1_runtime_activation_authorized",
        "NPU_authorized",
        "service_launch_authorized",
        "performance_experiment_authorized",
        "performance_claim_authorized",
        "M0_proven",
    ):
        assert gates[gate] is False


def test_reauthorization_candidate_binds_result_and_grants_nothing() -> None:
    candidate = _json(P1 / "g1-cpu-wiring-reauthorization-candidate.r2.json")
    chain = candidate["current_authority_chain"]
    assert chain["G0_mapping_remediation_CPU_result_sha256"] == _sha256(
        P1 / "g0-mapping-remediation-cpu-result.json"
    )
    assert chain["issue2_mapping_candidate_sha256"] == _sha256(
        P1 / "issue2-kv-recovery-mapping.v0-draft.md"
    )
    assert chain["Item4B_policy_sha256"] == _sha256(
        P1 / "kv-recovery-observer-policy.v0-draft.json"
    )
    assert chain["P0_overlay_sha256"] == _sha256(
        P1 / "kv-offload-base-mode-overlay.v0-draft.md"
    )
    assert candidate["candidate_effect"] == "none"
    assert (
        candidate["gate_effects"][
            "G1_CPU_side_source_work_reauthorized_for_current_digests"
        ]
        is False
    )
    assert candidate["gate_effects"]["G1_runtime_activation_authorized"] is False
    assert candidate["gate_effects"]["performance_experiment_authorized"] is False
