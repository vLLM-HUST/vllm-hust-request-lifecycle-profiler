from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime
from datetime import timezone
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
PROBE_PATH = REPO_ROOT / ".benchmarks" / "run_existing_server_trace_probe.py"


def _load_probe_module() -> Any:
    spec = importlib.util.spec_from_file_location("run_existing_server_trace_probe", PROBE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load probe module: {PROBE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _metric(summary: dict[str, Any], family: str, key: str) -> float | int | None:
    value = summary.get(family, {})
    if not isinstance(value, dict):
        return None
    return value.get(key)


def _mode_args(base_args: argparse.Namespace, *, mode: str) -> argparse.Namespace:
    args = deepcopy(base_args)
    args.observer_mode = mode
    args.output_dir = base_args.output_dir / mode
    args.trace_export_path = base_args.output_dir / f"{mode}_trace.jsonl"
    return args


def _write_probe_result(probe: Any, args: argparse.Namespace, result: dict[str, Any]) -> None:
    probe.write_outputs(args, result)


def _comparison(mode_results: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    by_mode: dict[str, dict[str, Any]] = {}
    for item in mode_results:
        mode = str(item["mode"])
        summary = item["result"]["summary"]
        row = {
            "mode": mode,
            "request_count": summary["request_count"],
            "success_count": summary["success_count"],
            "error_count": summary["error_count"],
            "event_count": summary["event_count"],
            "ttft_p50_ms": _metric(summary, "first_token_ms", "p50"),
            "ttft_p95_ms": _metric(summary, "first_token_ms", "p95"),
            "latency_p50_ms": _metric(summary, "latency_ms", "p50"),
            "latency_p95_ms": _metric(summary, "latency_ms", "p95"),
            "output_dir": str(item["output_dir"]),
        }
        rows.append(row)
        by_mode[mode] = row

    baseline = by_mode.get("no-trace")
    trace = by_mode.get("trace")
    deltas: dict[str, Any] = {}
    if baseline is not None and trace is not None:
        deltas = {
            "ttft_p50_delta_ms": (
                trace["ttft_p50_ms"] - baseline["ttft_p50_ms"]
                if trace["ttft_p50_ms"] is not None and baseline["ttft_p50_ms"] is not None
                else None
            ),
            "ttft_p95_delta_ms": (
                trace["ttft_p95_ms"] - baseline["ttft_p95_ms"]
                if trace["ttft_p95_ms"] is not None and baseline["ttft_p95_ms"] is not None
                else None
            ),
            "latency_p50_delta_ms": (
                trace["latency_p50_ms"] - baseline["latency_p50_ms"]
                if trace["latency_p50_ms"] is not None and baseline["latency_p50_ms"] is not None
                else None
            ),
            "latency_p95_delta_ms": (
                trace["latency_p95_ms"] - baseline["latency_p95_ms"]
                if trace["latency_p95_ms"] is not None and baseline["latency_p95_ms"] is not None
                else None
            ),
            "event_count_delta": trace["event_count"] - baseline["event_count"],
        }
    return {"modes": rows, "deltas": deltas}


def run_suite(args: argparse.Namespace) -> dict[str, Any]:
    probe = _load_probe_module()
    mode_results: list[dict[str, Any]] = []
    for mode in args.mode:
        mode_args = _mode_args(args, mode=mode)
        result = probe.run_probe(mode_args)
        _write_probe_result(probe, mode_args, result)
        mode_results.append({"mode": mode, "output_dir": mode_args.output_dir, "result": result})
    return {
        "metadata": {
            "evidence_label": "existing-server-probe",
            "result_valid_for_speedup_claims": False,
            "claim_boundary": (
                "Matched existing-server client-probe overhead suite. It compares the same workload "
                "with lifecycle event construction disabled and enabled in the probe process. This is "
                "not internal runtime hook overhead and must not be reported as vLLM scheduler/KV tracing cost."
            ),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "command": [Path(sys.argv[0]).name, *sys.argv[1:]],
            "modes": list(args.mode),
            "api_key_env": args.api_key_env,
            "api_key_present": bool(os.environ.get(args.api_key_env, "")),
        },
        "comparison": _comparison(mode_results),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run matched no-trace/trace existing-server probe overhead suite.")
    parser.add_argument("--endpoint", default=os.environ.get("VLLM_RLP_ENDPOINT", "http://127.0.0.1:18168"))
    parser.add_argument("--model", default=os.environ.get("VLLM_ENGINE_SERVED_MODEL_NAME", "codex-qwen2.5-7b-npu6"))
    parser.add_argument("--api-key-env", default="VLLM_HUST_API_KEY")
    parser.add_argument("--case-id", default="shared_scenario_multi_turn_knowledge_service")
    parser.add_argument("--max-requests", type=int, default=4)
    parser.add_argument("--warmup-requests", type=int, default=1)
    parser.add_argument("--repeat-count", type=int, default=3)
    parser.add_argument("--request-max-tokens", type=int, default=8)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--timeout-s", type=float, default=60.0)
    parser.add_argument("--mode", action="append", choices=("no-trace", "trace"))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / ".benchmarks" / "results" / "npu6_existing_server_trace_overhead_smoke",
    )
    parser.add_argument("--trace-export-path", type=Path, default=REPO_ROOT / ".benchmarks" / "results" / "unused.jsonl")
    args = parser.parse_args()
    if not args.mode:
        args.mode = ["no-trace", "trace"]
    return args


def main() -> None:
    args = parse_args()
    result = run_suite(args)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "run_metadata.json").write_text(
        json.dumps(result["metadata"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "overhead_summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result["comparison"], sort_keys=True))


if __name__ == "__main__":
    main()
