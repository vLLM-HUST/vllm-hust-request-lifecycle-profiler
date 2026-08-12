from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "verify_g0_pinned_pair.py"
RUNTIME_REPO = REPOSITORY_ROOT.parent / "vllm-hust"
DEVICE_REPO = REPOSITORY_ROOT.parent / "vllm-ascend-hust"
BENCHMARK_CANDIDATE = (
    REPOSITORY_ROOT
    / "contracts"
    / "p1"
    / "benchmark-134-fixed-8gib-config-candidate.json"
)


def _load_probe_module():
    spec = importlib.util.spec_from_file_location("g0_pinned_pair_probe", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PROBE = _load_probe_module()


@pytest.fixture(scope="module")
def audited_sibling_repositories() -> tuple[Path, Path]:
    required = (
        (RUNTIME_REPO, PROBE.RUNTIME_COMMIT),
        (DEVICE_REPO, PROBE.DEVICE_COMMIT),
    )
    for repository, commit in required:
        if not repository.is_dir():
            pytest.skip(
                "local G0 pin audit requires explicitly provisioned sibling "
                f"repository {repository}"
            )
        result = subprocess.run(
            ["git", "-C", str(repository), "cat-file", "-e", f"{commit}^{{commit}}"],
            check=False,
            capture_output=True,
        )
        if result.returncode != 0:
            pytest.skip(
                f"local G0 pin audit requires sibling commit {commit} in {repository}"
            )
    return RUNTIME_REPO, DEVICE_REPO


@pytest.fixture(scope="module")
def probe_result(
    audited_sibling_repositories: tuple[Path, Path],
) -> dict[str, object]:
    runtime_repo, device_repo = audited_sibling_repositories
    return PROBE.run_probe(runtime_repo, device_repo)


@pytest.fixture
def compatible_tiering_config() -> dict[str, object]:
    return {
        "runtime_commit": PROBE.RUNTIME_COMMIT,
        "device_plugin_commit": PROBE.DEVICE_COMMIT,
        "resolved_config": {
            "kv_cache_memory_bytes": 8 * 1024**3,
            "additional_config": {
                "recompute_scheduler_enable": False,
                "SLO_limits_for_dynamic_batch": -1,
            },
            "scheduler_config": {"scheduler_cls": None},
            "kv_transfer_config": {
                "kv_connector": "OffloadingConnector",
                "kv_role": "kv_both",
                "kv_connector_module_path": None,
                "kv_connector_extra_config": {
                    "spec_name": "TieringOffloadingSpec",
                    "cpu_bytes_to_use": 8 * 1024**3,
                },
            },
        },
    }


def _check_by_name(result: dict[str, object], name: str) -> dict[str, object]:
    checks = result["checks"]
    assert isinstance(checks, list)
    matches = [check for check in checks if check.get("name") == name]
    assert len(matches) == 1
    return matches[0]


def test_static_contract_passes_but_real_import_remains_blocked(
    probe_result: dict[str, object],
) -> None:
    assert probe_result["static_source_contract_status"] == "PASS_STATIC_ONLY"
    assert probe_result["overall_status"] == "BLOCKED"

    real_import = probe_result["real_pinned_import"]
    assert isinstance(real_import, dict)
    assert real_import["status"] == "BLOCKED"
    assert real_import["reason_code"] == "REAL_PINNED_IMPORT_ENVIRONMENT_UNPROVEN"
    assert "do not prove" in real_import["note"]


def test_scheduler_factory_and_negative_control_are_pinned(
    probe_result: dict[str, object],
) -> None:
    scheduler = _check_by_name(probe_result, "scheduler_call_and_override_contract")
    factory = _check_by_name(probe_result, "connector_spec_and_worker_factory_contract")
    negative = _check_by_name(probe_result, "legacy_device_npu_negative_control")

    assert scheduler["status"] == "PASS"
    scheduler_details = scheduler["details"]
    assert scheduler_details["engine_core_call_lines"] == [495, 552]
    assert scheduler_details["required_resolved_guards"] == {
        "recompute_scheduler_enable": False,
        "SLO_limits_for_dynamic_batch": -1,
        "scheduler_cls": None,
    }

    assert factory["status"] == "PASS"
    factory_details = factory["details"]
    assert factory_details["connector"][1] == "OffloadingConnector"
    assert factory_details["spec"][1] == "TieringOffloadingSpec"
    assert factory_details["device_connector_override"] is False

    assert negative["status"] == "PASS"
    negative_details = negative["details"]
    assert negative_details["runtime_path_exists"] is False
    assert negative_details["device_import"].endswith("worker.worker")


def test_controlled_stub_separates_worker_handoff_from_observer_ledger(
    probe_result: dict[str, object],
) -> None:
    handoff = _check_by_name(
        probe_result, "controlled_stub_worker_job_handoff_and_observer_ledger"
    )
    assert handoff["status"] == "PASS"
    details = handoff["details"]
    assert details["evidence_kind"] == (
        "controlled_stub_pinned_worker_plus_separate_observer_ledger"
    )
    assert details["runtime_wiring_proven"] is False
    assert details["profile_identity_propagation_proven"] is False
    assert set(details["pinned_worker_preserved_fields"]) == {
        "connector_job_id",
        "runtime_request_id",
        "source_spec",
        "destination_spec",
        "wait_set_job_ids",
    }
    assert "recovery_epoch" in details["observer_ledger_only_fields"]
    assert "logical_block_set" in details["observer_ledger_only_fields"]
    assert details["recovery_epoch"] == 1
    assert details["bytes_moved"] == 8192
    assert details["device_duration_ns"] == 12_500_000
    assert details["wait_set"] == [7]
    assert set(details["observer_ledger_negative_rejections"]) == {
        "request_identity_drift",
        "logical_block_drift",
        "duplicate_completion",
        "unknown_completion",
        "failed_completion",
        "zero_size_completion",
    }


def test_optional_tiering_config_fixture_is_source_compatible_only(
    compatible_tiering_config: dict[str, object],
) -> None:
    result = PROBE.validate_config_candidate_data(compatible_tiering_config)
    assert result == {
        "status": "PASS_SOURCE_COMPATIBILITY_ONLY",
        "implementation_family": "runtime_core_offloading_connector",
        "formal_communication_admission": False,
    }


def test_real_incomplete_benchmark_candidate_is_reviewed_but_remains_blocked() -> None:
    result = PROBE.validate_config_candidate(BENCHMARK_CANDIDATE)
    assert result["status"] == "BLOCKED_INCOMPLETE_CONFIGURATION_CANDIDATE_REVIEWED"
    assert result["implementation_family"] == "mixed_three_mode_candidate"
    assert result["formal_communication_admission"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        lambda candidate: candidate["runnability"].update(
            NPU_execution_authorized=True
        ),
        lambda candidate: candidate["approved_context"].update(not_granted=[]),
        lambda candidate: candidate["mutually_exclusive_modes"][2][
            "runtime_resolution"
        ].update(spec_name="NPUTieringOffloadingSpec"),
        lambda candidate: candidate["mutually_exclusive_modes"].append(
            "unreviewed-mode"
        ),
        lambda candidate: candidate["gate_effects"].update(
            communication_mode_non_none_unblocked=True
        ),
        lambda candidate: candidate["mutually_exclusive_modes"][2][
            "known_kv_transfer_fragment"
        ].update(kv_role="kv_producer"),
        lambda candidate: candidate["mutually_exclusive_modes"][1][
            "proposed_non_executable_resolution"
        ].update(spec_module_path_policy="vllm_ascend.kv_offload.npu"),
        lambda candidate: candidate["mutually_exclusive_modes"][2][
            "runtime_resolution"
        ].update(spec_class="NPUTieringOffloadingSpec"),
        lambda candidate: candidate["repeat_policy"].update(
            execution_status="AUTHORIZED"
        ),
        lambda candidate: candidate["gate_effects"].update(
            unreviewed_authorization=True
        ),
    ],
)
def test_incomplete_candidate_rejects_gate_sensitive_drift(mutation) -> None:
    candidate = json.loads(BENCHMARK_CANDIDATE.read_text(encoding="utf-8"))
    mutation(candidate)
    with pytest.raises(PROBE.ProbeFailure, match="semantic digest mismatch"):
        PROBE.validate_config_candidate_data(candidate)


def test_optional_hbm_config_fixture_keeps_no_connector(
    compatible_tiering_config: dict[str, object],
) -> None:
    hbm_config = deepcopy(compatible_tiering_config)
    hbm_config["resolved_config"]["kv_transfer_config"] = None
    result = PROBE.validate_config_candidate_data(hbm_config)
    assert result["implementation_family"] == "hbm_only_no_connector"
    assert result["formal_communication_admission"] is False


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda config: config["resolved_config"]["additional_config"].update(
                recompute_scheduler_enable=True
            ),
            "recompute_scheduler_enable",
        ),
        (
            lambda config: config["resolved_config"]["additional_config"].update(
                SLO_limits_for_dynamic_batch=10
            ),
            "SLO_limits_for_dynamic_batch",
        ),
        (
            lambda config: config["resolved_config"]["scheduler_config"].update(
                scheduler_cls=(
                    "vllm_ascend.core.scheduler_dynamic_batch.SchedulerDynamicBatch"
                )
            ),
            "scheduler_cls",
        ),
        (
            lambda config: config["resolved_config"]["kv_transfer_config"][
                "kv_connector_extra_config"
            ].update(spec_module_path="vllm_ascend.kv_offload.npu"),
            "spec_module_path",
        ),
    ],
)
def test_config_rejects_every_known_incompatible_override(
    compatible_tiering_config: dict[str, object], mutation, message: str
) -> None:
    candidate = deepcopy(compatible_tiering_config)
    mutation(candidate)
    with pytest.raises(PROBE.ProbeFailure, match=message):
        PROBE.validate_config_candidate_data(candidate)


@pytest.mark.parametrize("cpu_bytes_to_use", [None, 0, -1, False, 1.5, "8589934592"])
def test_config_rejects_nonpositive_or_noninteger_cpu_capacity(
    compatible_tiering_config: dict[str, object], cpu_bytes_to_use: object
) -> None:
    candidate = deepcopy(compatible_tiering_config)
    candidate["resolved_config"]["kv_transfer_config"]["kv_connector_extra_config"][
        "cpu_bytes_to_use"
    ] = cpu_bytes_to_use
    with pytest.raises(PROBE.ProbeFailure, match="cpu_bytes_to_use"):
        PROBE.validate_config_candidate_data(candidate)


def test_cli_accepts_optional_config_but_exits_blocked(
    tmp_path: Path,
    compatible_tiering_config: dict[str, object],
    audited_sibling_repositories: tuple[Path, Path],
) -> None:
    runtime_repo, device_repo = audited_sibling_repositories
    config_path = tmp_path / "resolved-config.json"
    config_path.write_text(
        json.dumps(compatible_tiering_config, sort_keys=True), encoding="utf-8"
    )
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--runtime-repo",
            str(runtime_repo),
            "--device-repo",
            str(device_repo),
            "--config",
            str(config_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == PROBE.EXIT_BLOCKED, result.stderr
    payload = json.loads(result.stdout)
    assert payload["overall_status"] == "BLOCKED"
    assert payload["static_source_contract_status"] == "PASS_STATIC_ONLY"
    assert payload["configuration_candidates"][0]["status"] == (
        "PASS_SOURCE_COMPATIBILITY_ONLY"
    )
    assert payload["real_pinned_import"]["status"] == "BLOCKED"
