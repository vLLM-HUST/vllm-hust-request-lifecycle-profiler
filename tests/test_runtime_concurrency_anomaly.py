from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_module():
    path = (
        Path(__file__).resolve().parents[1]
        / ".benchmarks"
        / "analyze_runtime_concurrency_anomaly.py"
    )
    spec = importlib.util.spec_from_file_location("analyze_runtime_concurrency_anomaly", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _runtime_events(chain_id: str, start_ms: float, *, prefill_ms: float) -> list[dict]:
    internal_id = f"{chain_id}-i"
    return [
        {
            "request_id": chain_id,
            "stage": "received",
            "timestamp_ms": start_ms,
            "metadata": {
                "prompt_tokens": 100,
                "max_tokens": 8,
                "observer": "vllm_runtime_hook",
            },
        },
        {
            "request_id": chain_id,
            "stage": "tokenized",
            "timestamp_ms": start_ms + 1,
            "metadata": {"observer": "vllm_runtime_hook"},
        },
        {
            "request_id": chain_id,
            "stage": "queued",
            "timestamp_ms": start_ms + 2,
            "metadata": {"observer": "vllm_runtime_hook"},
        },
        {
            "request_id": internal_id,
            "stage": "scheduled",
            "timestamp_ms": start_ms + 3,
            "metadata": {
                "external_request_id": chain_id,
                "prompt_tokens": 100,
                "observer": "vllm_runtime_hook",
            },
        },
        {
            "request_id": internal_id,
            "stage": "prefill_done",
            "timestamp_ms": start_ms + 3 + prefill_ms,
            "metadata": {
                "external_request_id": chain_id,
                "prompt_tokens": 100,
                "cached_tokens": 96,
                "observer": "vllm_runtime_hook",
            },
        },
        {
            "request_id": internal_id,
            "stage": "first_token",
            "timestamp_ms": start_ms + 3 + prefill_ms,
            "metadata": {
                "external_request_id": chain_id,
                "prompt_tokens": 100,
                "observer": "vllm_runtime_hook",
            },
        },
        {
            "request_id": internal_id,
            "stage": "decode_done",
            "timestamp_ms": start_ms + 13 + prefill_ms,
            "metadata": {
                "external_request_id": chain_id,
                "generation_tokens": 8,
                "observer": "vllm_runtime_hook",
            },
        },
        {
            "request_id": internal_id,
            "stage": "stream_done",
            "timestamp_ms": start_ms + 14 + prefill_ms,
            "metadata": {
                "external_request_id": chain_id,
                "generation_tokens": 8,
                "observer": "vllm_runtime_hook",
            },
        },
        {
            "request_id": internal_id,
            "stage": "cleanup_done",
            "timestamp_ms": start_ms + 15 + prefill_ms,
            "metadata": {
                "external_request_id": chain_id,
                "observer": "vllm_runtime_hook",
            },
        },
    ]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_runtime_concurrency_anomaly_finds_c2_prefill_outlier(tmp_path: Path) -> None:
    module = _load_module()
    input_dir = tmp_path / "sweep"
    runtime_trace = input_dir / "runtime_trace.jsonl"
    events: list[dict] = []
    start = 0.0
    for index in range(30):
        prefill_ms = 5000.0 if index == 11 else 50.0
        events.extend(_runtime_events(f"req-{index}", start, prefill_ms=prefill_ms))
        start += 100.0 + prefill_ms
    _write_jsonl(runtime_trace, events)
    for concurrency in (1, 2, 3):
        _write_jsonl(
            input_dir / f"concurrency_{concurrency}" / "client_proxy_trace.jsonl",
            [{"timestamp_ms": float(concurrency)}],
        )

    args = module.parse_args(
        [
            "--input-dir",
            str(input_dir),
            "--runtime-trace",
            str(runtime_trace),
            "--output-dir",
            str(input_dir / "analysis"),
        ]
    )
    result = module.build_analysis(args)

    assert result["metadata"]["parent_repo"]["dirty_exclusion_dir"] == str(
        input_dir / "analysis"
    )
    assert "dirty_excluding_output_dir" in result["metadata"]["parent_repo"]
    assert result["summary"]["measured_chain_count"] == 27
    assert result["summary"]["prefill_outlier_count"] == 1
    assert result["summary"]["prefill_outlier_concurrency_values"] == [2]
    assert result["summary"]["diagnosis"] == {
        "stage_localization": "prefill",
        "stage_localization_status": "localized",
        "root_cause_status": "unresolved",
        "root_cause_candidates_not_distinguished": [
            "scheduler_to_prefill",
            "kv_allocation_cache_pressure",
            "graph_batch_transition",
            "prefill_kernel_execution",
        ],
    }
    requirements = result["summary"]["required_subprefill_instrumentation"]
    assert {row["component"] for row in requirements} == {
        "scheduler_to_prefill",
        "kv_allocation_cache_pressure",
        "graph_batch_transition",
        "prefill_kernel_execution",
    }
    assert all(row["status"] == "missing" for row in requirements)
    assert all(row["missing_fields"] for row in requirements)
    c2 = result["summary"]["per_concurrency"][1]
    assert c2["prompt_token_values"] == [100]
    assert c2["generation_token_values"] == [8]
    assert c2["cached_token_ratio"]["p50"] == 0.96
