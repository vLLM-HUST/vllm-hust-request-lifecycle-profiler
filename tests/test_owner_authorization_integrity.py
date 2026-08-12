from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
P1 = REPOSITORY_ROOT / "contracts" / "p1"

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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_historical_overlay_ratification_record_is_preserved_and_freezes_nothing() -> (
    None
):
    record = _json(P1 / "kv-offload-base-mode-overlay-owner-approval.json")
    artifacts = {item["role"]: item for item in record["proposed_artifacts"]}
    assert artifacts["P0_base_mode_overlay"]["sha256"] == HISTORICAL_OVERLAY_SHA256
    assert artifacts["overlay_approval_candidate"]["sha256"] == (
        HISTORICAL_OVERLAY_CANDIDATE_SHA256
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
    assert (
        record["approval_source"]["resolved_context_at_recording"]["overlay_sha256"]
        == HISTORICAL_OVERLAY_SHA256
    )
    assert record["gate_effects"]["P0_overlay_frozen"] is False
    assert record["gate_effects"]["issue2_mapping_frozen"] is False
    assert record["gate_effects"]["communication_mode_non_none_authorized"] is False


def test_historical_G1_authorization_keeps_activation_closed() -> None:
    authorization = _json(P1 / "g1-cpu-wiring-owner-authorization.json")
    chain = authorization["authority_chain"]
    assert chain["recovery_profile_sha256"] == _sha256(
        P1 / "kv-recovery-profile.v0-draft.md"
    )
    assert chain["profile_owner_approval_record_sha256"] == _sha256(
        P1 / "kv-recovery-profile-owner-approval.json"
    )
    assert chain["issue2_mapping_candidate_sha256"] == HISTORICAL_MAPPING_SHA256
    assert chain["issue2_mapping_approval_candidate_sha256"] == (
        HISTORICAL_MAPPING_CANDIDATE_SHA256
    )
    assert chain["P0_overlay_sha256"] == HISTORICAL_OVERLAY_SHA256
    assert chain["P0_overlay_approval_candidate_sha256"] == (
        HISTORICAL_OVERLAY_CANDIDATE_SHA256
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
