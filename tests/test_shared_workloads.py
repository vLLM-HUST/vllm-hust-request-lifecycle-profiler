from __future__ import annotations

from vllm_request_lifecycle_profiler.shared_workloads import build_shared_workload_report
from vllm_request_lifecycle_profiler.shared_workloads import generate_case_requests
from vllm_request_lifecycle_profiler.shared_workloads import supported_shared_case_ids


def test_supported_shared_case_ids_are_available() -> None:
	case_ids = supported_shared_case_ids()
	assert case_ids
	assert "shared_scenario_multi_turn_knowledge_service" in case_ids


def test_generate_case_requests_emits_rows_for_supported_case() -> None:
	rows = generate_case_requests("shared_scenario_multi_turn_knowledge_service", seed=7)
	assert rows
	assert rows[0].prompt_len > 0
	assert rows[0].output_len > 0


def test_build_shared_workload_report_covers_repo_local_cases() -> None:
	report = build_shared_workload_report(seed=7)
	assert report["supported_case_count"] > 0
	assert report["supported_cases"]
	assert any(case["case_id"] == "shared_public_sharegpt_boundary" for case in report["skipped_cases"])