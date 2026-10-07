"""ECPA 0.3 manifest and package ownership checks."""

from __future__ import annotations

import json
from pathlib import Path

BUNDLE_ID = "org.vllm-hust.request-lifecycle-profiler"
MANIFEST = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "vllm_request_lifecycle_profiler"
    / "manifests"
    / "vllm-hust-extension-v0.3.json"
)


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_ecpa_manifest_is_static_and_versioned() -> None:
    value = load_manifest()
    assert value["schema_version"] == "0.3-experimental"
    assert value["extension_id"] == BUNDLE_ID
    assert value["extension_version"] == "0.1.0"
    assert value["host"] == {
        "provider": "vllm",
        "name": "vllm",
        "version_range": ">=0.29.1,<0.30",
        "api_range": ">=1,<2",
    }


def test_historical_carrier_fails_closed() -> None:
    value = load_manifest()
    assert value["implementation"][0]["status"] == "legacy_unregistered"
    assert value["activation"]["entry_points"] == [
        {"group": "vllm.general_plugins", "name": "request_lifecycle_profiler"}
    ]


def test_native_event_contract_and_shared_observer_are_declared() -> None:
    value = load_manifest()
    assert {
        "name": "vllm.request-lifecycle-events",
        "version_range": ">=1,<2",
    } in value["protocols"]
    assert value["resource_claims"] == [
        {
            "resource": "vllm.request-lifecycle-events.observer",
            "scope": "vllm-process",
            "mode": "shared",
        }
    ]


def test_manifest_import_does_not_import_vllm() -> None:
    import sys

    assert "vllm" not in sys.modules
