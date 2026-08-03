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


def test_overlay_ratification_record_binds_bytes_but_freezes_nothing() -> None:
    record = _json(P1 / "kv-offload-base-mode-overlay-owner-approval.json")
    artifacts = {item["role"]: item for item in record["proposed_artifacts"]}
    assert artifacts["P0_base_mode_overlay"]["sha256"] == _sha256(
        P1 / "kv-offload-base-mode-overlay.v0-draft.md"
    )
    assert artifacts["overlay_approval_candidate"]["sha256"] == _sha256(
        P1 / "kv-offload-base-mode-overlay-approval-candidate.json"
    )
    assert record["accepted_decisions"]["accepted_items"] == []
    assert record["approval_source"]["exact_user_statement"] == (
        "我现在将我能批准的权限全部批准，然后按照你说的做"
    )
    assert record["approval_source"]["incorporated_referenced_scope"] == (
        "创建当前 G0 Draft PR，并批准开始独立分支上的 G1 CPU-side runtime "
        "wiring；实现必须默认关闭，绑定当前 mapping/profile/overlay 候选摘要。"
        "该授权不激活 communication_mode 非 none，不授权 NPU、服务启动或性能实验。"
    )
    assert record["approval_source"]["resolved_context_at_recording"][
        "overlay_sha256"
    ] == _sha256(P1 / "kv-offload-base-mode-overlay.v0-draft.md")
    assert record["gate_effects"]["P0_overlay_frozen"] is False
    assert record["gate_effects"]["issue2_mapping_frozen"] is False
    assert record["gate_effects"]["communication_mode_non_none_authorized"] is False


def test_G1_authorization_binds_authority_chain_and_keeps_activation_closed() -> None:
    authorization = _json(P1 / "g1-cpu-wiring-owner-authorization.json")
    chain = authorization["authority_chain"]
    assert chain["recovery_profile_sha256"] == _sha256(
        P1 / "kv-recovery-profile.v0-draft.md"
    )
    assert chain["profile_owner_approval_record_sha256"] == _sha256(
        P1 / "kv-recovery-profile-owner-approval.json"
    )
    assert chain["issue2_mapping_candidate_sha256"] == _sha256(
        P1 / "issue2-kv-recovery-mapping.v0-draft.md"
    )
    assert chain["issue2_mapping_approval_candidate_sha256"] == _sha256(
        P1 / "issue2-kv-recovery-mapping-approval-candidate.json"
    )
    assert chain["P0_overlay_sha256"] == _sha256(
        P1 / "kv-offload-base-mode-overlay.v0-draft.md"
    )
    assert chain["P0_overlay_approval_candidate_sha256"] == _sha256(
        P1 / "kv-offload-base-mode-overlay-approval-candidate.json"
    )
    assert chain["P0_overlay_pending_ratification_record_sha256"] == _sha256(
        P1 / "kv-offload-base-mode-overlay-owner-approval.json"
    )
    assert chain["G0_CPU_result_sha256"] == _sha256(
        P1 / "g0-pinned-pair-cpu-result.json"
    )

    gates = authorization["gate_effects"]
    assert gates["G1_CPU_side_source_implementation_authorized"] is True
    assert gates["P0_overlay_frozen"] is False
    assert gates["G1_runtime_activation_authorized"] is False
    assert gates["communication_mode_non_none_authorized"] is False
    assert gates["device_plugin_source_edits_authorized"] is False
    assert gates["NPU_authorized"] is False
    assert gates["service_launch_authorized"] is False
    assert gates["performance_experiment_authorized"] is False
    assert authorization["implementation_constraints"]["default_enabled"] is False
    assert (
        authorization["implementation_constraints"][
            "max_pending_h2d_contexts_per_process"
        ]
        == 4096
    )
