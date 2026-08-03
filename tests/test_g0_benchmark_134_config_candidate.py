from __future__ import annotations

import json
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_PATH = (
    REPOSITORY_ROOT
    / "contracts"
    / "p1"
    / "benchmark-134-fixed-8gib-config-candidate.json"
)


@pytest.fixture(scope="module")
def candidate() -> dict[str, object]:
    payload = json.loads(CANDIDATE_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _mode(candidate: dict[str, object], mode_id: str) -> dict[str, object]:
    modes = candidate["mutually_exclusive_modes"]
    assert isinstance(modes, list)
    matches = [mode for mode in modes if mode["mode_id"] == mode_id]
    assert len(matches) == 1
    return matches[0]


def test_candidate_is_explicitly_incomplete_and_non_authorizing(
    candidate: dict[str, object],
) -> None:
    assert candidate["status"] == "BLOCKED_INCOMPLETE_NOT_RUNNABLE_NOT_FROZEN"
    assert candidate["evidence_status"] == "NOT_M0_PROVEN"

    runnability = candidate["runnability"]
    assert runnability["is_fully_resolved"] is False
    assert runnability["is_runnable"] is False
    assert runnability["is_frozen_by_authority"] is False
    assert runnability["service_launch_authorized"] is False
    assert runnability["NPU_execution_authorized"] is False
    assert runnability["performance_experiment_authorized"] is False

    gates = candidate["gate_effects"]
    assert gates["G0_complete"] is False
    assert gates["G1_unblocked"] is False
    assert gates["communication_mode_non_none_unblocked"] is False
    assert gates["M0_proven"] is False


def test_common_capacity_and_scheduler_guards_are_exact(
    candidate: dict[str, object],
) -> None:
    common = candidate["fixed_common_parameters"]
    capacity = common["device_kv_capacity"]
    assert capacity == {
        "unit_system": "IEC_binary",
        "unit_name": "GiB",
        "bytes_per_GiB": 1_073_741_824,
        "requested_GiB_per_device": 8,
        "bytes_per_device": 8_589_934_592,
        "logical_device_count": 1,
        "aggregate_device_KV_bytes": 8_589_934_592,
        "scope": "exact_KV_cache_bytes_per_logical_device",
        "runtime_field": "kv_cache_memory_bytes",
        "not_derived_from_gpu_memory_utilization": True,
    }

    server = common["server_semantic_config"]
    assert server["dtype"] == "float16"
    assert server["max_model_len"] == 32768
    assert server["kv_cache_memory_bytes"] == 8_589_934_592
    assert server["gpu_memory_utilization"] == 0.6
    assert server["scheduler_cls"] is None
    assert server["disable_log_stats"] is False
    assert server["additional_config"] == {
        "SLO_limits_for_dynamic_batch": -1,
        "recompute_scheduler_enable": False,
    }

    guards = common["scheduler_guards"]
    assert guards["required_result"] == "runtime_Scheduler_or_AsyncScheduler_only"
    assert set(guards["forbidden_resolved_classes"]) == {
        "vllm_ascend.core.recompute_scheduler.RecomputeScheduler",
        "vllm_ascend.core.recompute_scheduler.AsyncRecomputeScheduler",
        "vllm_ascend.core.scheduler_dynamic_batch.SchedulerDynamicBatch",
    }
    assert guards["requested_scheduler_cls"] is None


def test_three_modes_are_unique_and_fail_closed(candidate: dict[str, object]) -> None:
    modes = candidate["mutually_exclusive_modes"]
    assert [mode["mode_id"] for mode in modes] == [
        "hbm_only_no_connector",
        "tiering_disabled",
        "tiering_enabled",
    ]

    hbm = _mode(candidate, "hbm_only_no_connector")
    assert hbm["connector_present"] is False
    assert hbm["known_kv_transfer_config"] is None
    assert hbm["communication"]["communication_mode"] == "none"

    disabled = _mode(candidate, "tiering_disabled")
    assert disabled["mode_status"] == (
        "BLOCKED_PENDING_SEMANTIC_PROFILE_FAMILY_AND_OVERLAY_AUTHORITY"
    )
    assert disabled["profile_compatibility"]["status"] == (
        "OUTSIDE_CURRENT_PROFILE_OWNER_IMPLEMENTATION_DECISION"
    )
    proposed = disabled["proposed_non_executable_resolution"]
    assert proposed["connector_name"] == "OffloadingConnector"
    assert proposed["spec_name"] == "CPUOffloadingSpec"
    assert proposed["cpu_bytes_to_use"] is None

    enabled = _mode(candidate, "tiering_enabled")
    assert enabled["connector_present"] is True
    resolution = enabled["runtime_resolution"]
    assert resolution["connector_name"] == "OffloadingConnector"
    assert resolution["spec_name"] == "TieringOffloadingSpec"
    assert resolution["connector_module_path_policy"] == "OMIT"
    assert resolution["spec_module_path_policy"] == "OMIT"
    assert resolution["device_plugin_NPUTieringOffloadingSpec_allowed"] is False

    transfer = enabled["known_kv_transfer_fragment"]
    assert transfer["cpu_bytes_to_use"] is None
    extra = transfer["kv_connector_extra_config_without_blocked_cpu_bytes"]
    assert extra["tiering_reclaim_device_cache_after_store"] is True
    assert "tiering_reclaim_device_after_store" not in extra
    assert "spec_module_path" not in extra


def test_all_authority_inputs_remain_explicit_blockers(
    candidate: dict[str, object],
) -> None:
    blockers = candidate["blocked_decisions"]
    assert {blocker["code"] for blocker in blockers} == {
        "BLOCKED_CPU_BYTES_TO_USE",
        "BLOCKED_MODEL_REVISION",
        "BLOCKED_REQUEST_MANIFESTS",
        "BLOCKED_TIERING_DISABLED_SEMANTICS",
        "BLOCKED_COPY_OPTIMIZATION_TOGGLE",
        "BLOCKED_COMMUNICATION_MAPPING",
        "BLOCKED_COMMON_PARAMETER_AUTHORITY",
        "BLOCKED_P0_BASE_MODE_OVERLAY",
        "BLOCKED_METRIC_COVERAGE",
    }

    model = candidate["fixed_common_parameters"]["model"]
    assert model["revision"] is None
    assert model["authority_frozen_local_path"] is None
    observation = model["local_observation_not_authority_frozen"]
    assert observation["observed_revision"] == (
        "cf98f3b3bbb457ad9e2bb7baf9a0125b6b88caa8"
    )
    assert observation["effect"] == "availability_evidence_only_not_a_revision_freeze"

    copy_pair = candidate["copy_optimization_pair"]
    assert copy_pair["status"] == "BLOCKED_NO_UNIQUE_ON_OFF_SWITCH_AT_PINNED_SHAS"
    assert copy_pair["on_configuration"] is None
    assert copy_pair["off_configuration"] is None

    metric_candidate = candidate["metric_collection_candidate"]
    assert metric_candidate["status"] == (
        "BLOCKED_PENDING_EXACT_METRIC_SOURCE_AND_COVERAGE_VALIDATION"
    )
    assert metric_candidate["disable_log_stats"] is False

    overhead = candidate["profiler_overhead_axis"]
    assert overhead["status"] == (
        "REQUIRED_FUTURE_SEPARATE_ONE_VARIABLE_PAIR_NOT_AUTHORIZED_TO_RUN"
    )


def test_workload_shapes_are_proposals_but_manifests_are_unresolved(
    candidate: dict[str, object],
) -> None:
    scenarios = {
        scenario["id"]: scenario for scenario in candidate["workloads"]["scenarios"]
    }
    assert scenarios["random_online"]["input_len"] == 1024
    assert scenarios["random_online"]["output_len"] == 256
    assert scenarios["random_online"]["random_range_ratio"] == 0.0
    assert scenarios["prefix_repetition_online"]["prefix_count"] == 10
    assert scenarios["prefix_repetition_online"]["prefix_len"] == 3840
    assert scenarios["prefix_repetition_online"]["suffix_len"] == 256
    assert scenarios["prefix_repetition_online"]["output_len"] == 256

    for scenario in scenarios.values():
        assert scenario["request_manifest_path"] is None
        assert scenario["request_manifest_sha256"] is None
        assert scenario["request_manifest_status"].startswith("BLOCKED_")

    cli = candidate["fixed_common_parameters"][
        "non_runnable_candidate_server_cli_fragment"
    ]
    assert "--disable-log-requests" not in cli
    assert "--disable-log-stats" not in cli
    assert "--kv-cache-memory-bytes=8589934592" in cli
    assert candidate["fixed_common_parameters"]["runnable_server_argv"] is None

    repeat = candidate["repeat_policy"]
    assert repeat["minimum_independent_service_lifecycles_per_workload_mode_pair"] == 3
