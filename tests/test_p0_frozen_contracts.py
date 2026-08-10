from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
P0 = REPOSITORY_ROOT / "contracts" / "p0"

EXPECTED_ARTIFACTS = {
    "minimum_runtime_contract": {
        "path": "runtime/minimum-runtime-contract.v0-draft.md",
        "sha256": ("122963930919073179d4844422d21e85da3a522def3ace723eb992eac43cdade"),
        "manifest_key": "minimum_runtime_contract_sha256",
    },
    "phase_taxonomy": {
        "path": "runtime/phase-taxonomy.v0-draft.md",
        "sha256": ("82aae94c5d124b846f77684e239714d51791115608e786079c4ea4bd4ca05abd"),
        "manifest_key": "phase_taxonomy_sha256",
    },
}

EXPECTED_P1_SCOPE = {
    "communication_mode": "none",
    "device_plugin_commit": "cafad89a5e103f31ea517c1edb56130578c3cd56",
    "device_plugin_repository": "vLLM-HUST/vllm-ascend-hust",
    "issue_2_dependency_preserved_for_non_none_modes": True,
    "issue_2_profile": None,
    "runtime_commit": "f229ba7cad21a4dba58681af6738a9fd947388e2",
    "runtime_repository": "vLLM-HUST/vllm-hust",
}


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_p0_owner_freeze_binds_the_approved_artifact_bytes() -> None:
    manifest = _load_json(P0 / "p0-manifest.json")
    approval = _load_json(P0 / "owner-freeze-approval.json")

    assert manifest["status"] == "owner_frozen"
    assert manifest["owner_freeze"]["status"] == "approved"
    assert manifest["owner_freeze"]["record"] == "owner-freeze-approval.json"
    assert approval["status"] == "owner_approved"
    assert approval["contract_approval"]["accepted_items"] == list(range(1, 9))
    assert approval["p1_scope"] == EXPECTED_P1_SCOPE

    approved_artifacts = {
        artifact["role"]: artifact for artifact in approval["approved_artifacts"]
    }
    assert set(approved_artifacts) == set(EXPECTED_ARTIFACTS)

    for role, expected in EXPECTED_ARTIFACTS.items():
        artifact = approved_artifacts[role]
        path = P0 / expected["path"]
        assert artifact["path"] == expected["path"]
        assert artifact["sha256"] == expected["sha256"]
        assert _sha256(path) == expected["sha256"]
        assert manifest["owner_freeze"][expected["manifest_key"]] == expected["sha256"]


if __name__ == "__main__":
    test_p0_owner_freeze_binds_the_approved_artifact_bytes()
