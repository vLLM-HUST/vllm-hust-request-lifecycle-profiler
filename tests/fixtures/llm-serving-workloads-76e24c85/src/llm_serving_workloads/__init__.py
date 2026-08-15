"""Minimal independent fixture for the shared-workload adapter tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

PINNED_WORKLOAD_COMMIT = "76e24c85bcab76ecfabb831c9444002b6efffd58"
_REPO_LOCAL_DATASET = "session-affine-multi-turn"

DEFAULT_SHARED_BENCHMARK_CASE_ORDER = (
    "shared_scenario_multi_turn_knowledge_service",
    "shared_public_sharegpt_boundary",
)

SHARED_BENCHMARK_CASE_CATALOG: dict[str, dict[str, Any]] = {
    "shared_scenario_multi_turn_knowledge_service": {
        "case_id": "shared_scenario_multi_turn_knowledge_service",
        "label": "Scenario: multi-turn knowledge service",
        "dataset_name": _REPO_LOCAL_DATASET,
        "dp_size": 8,
        "num_groups": 8,
        "prompts_per_group": 4,
        "system_prompt_len": 512,
        "question_len": 64,
        "output_len": 64,
        "benchmark_kwargs": {"session_turn_history": 4},
    },
    "shared_public_sharegpt_boundary": {
        "case_id": "shared_public_sharegpt_boundary",
        "label": "Public boundary: ShareGPT conversation mix",
        "dataset_name": "sharegpt",
        "dp_size": 8,
        "num_groups": 4,
        "prompts_per_group": 8,
        "num_prompts": 32,
        "system_prompt_len": 512,
        "question_len": 64,
        "output_len": 64,
        "benchmark_kwargs": {},
    },
}


@dataclass(frozen=True)
class _Request:
    prompt_len: int
    output_len: int
    repo_local_metadata: dict[str, Any]


def is_repo_local_workload_dataset(dataset_name: str) -> bool:
    return dataset_name == _REPO_LOCAL_DATASET


def generate_repo_local_workload_requests(
    *,
    dataset_name: str,
    tokenizer: Any,
    dp_size: int,
    num_prompts: int,
    num_groups: int,
    system_prompt_len: int,
    question_len: int,
    output_len: int,
    seed: int,
    **benchmark_kwargs: Any,
) -> list[_Request]:
    del tokenizer, seed, benchmark_kwargs
    if dataset_name != _REPO_LOCAL_DATASET:
        raise ValueError(f"unsupported fixture dataset: {dataset_name}")
    return [
        _Request(
            prompt_len=system_prompt_len + question_len,
            output_len=output_len,
            repo_local_metadata={
                "workload_family": dataset_name,
                "primary_anchor_id": f"session-{index % num_groups}",
                "secondary_anchor_ids": [f"tenant-{index % 2}"],
                "home_rank": index % dp_size,
            },
        )
        for index in range(num_prompts)
    ]


def summarize_repo_local_workload(requests: list[Any]) -> dict[str, Any] | None:
    if not requests:
        return None
    primary = {
        str(request.repo_local_metadata["primary_anchor_id"]) for request in requests
    }
    secondary = {
        str(anchor)
        for request in requests
        for anchor in request.repo_local_metadata["secondary_anchor_ids"]
    }
    ranks = {int(request.repo_local_metadata["home_rank"]) for request in requests}
    return {
        "workload_family": _REPO_LOCAL_DATASET,
        "request_count": len(requests),
        "primary_anchor_count": len(primary),
        "secondary_anchor_count": len(secondary),
        "anchor_rank_coverage": len(ranks),
    }
