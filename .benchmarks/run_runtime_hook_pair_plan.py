from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
from datetime import timezone
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DISABLED_DIR = (
    REPO_ROOT
    / ".benchmarks"
    / "results"
    / "npu6_runtime_hooks_disabled_low_overhead_baseline"
)
DEFAULT_ENABLED_DIR = (
    REPO_ROOT
    / ".benchmarks"
    / "results"
    / "npu6_runtime_hooks_low_overhead_enabled_smoke"
)
DEFAULT_TRACE_PATH = DEFAULT_ENABLED_DIR / "runtime_trace.jsonl"
EXPECTED_RUNTIME_STAGES = {
    "received",
    "tokenized",
    "queued",
    "scheduled",
    "prefill_done",
    "first_token",
    "decode_done",
    "stream_done",
    "cleanup_done",
}


def _git_text(args: list[str], *, cwd: Path = REPO_ROOT) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=cwd, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _git_dirty(cwd: Path) -> bool:
    return bool(_git_text(["status", "--short"], cwd=cwd))


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _metric(summary: dict[str, Any], family: str, key: str) -> float | int | None:
    value = summary.get(family, {})
    if not isinstance(value, dict):
        return None
    return value.get(key)


def _trace_bytes(path: Path) -> int | None:
    if not path.exists():
        return None
    return path.stat().st_size


def _trace_summary(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    stages: Counter[str] = Counter()
    observers: Counter[str] = Counter()
    request_ids: set[str] = set()
    chain_stages: dict[str, set[str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        stage = str(row.get("stage", ""))
        stages[stage] += 1
        request_id = str(row.get("request_id", ""))
        request_ids.add(request_id)
        metadata = row.get("metadata", {})
        observer = metadata.get("observer", "") if isinstance(metadata, dict) else ""
        observers[str(observer)] += 1
        external_request_id = (
            metadata.get("external_request_id") if isinstance(metadata, dict) else None
        )
        chain_id = str(external_request_id or request_id)
        chain_stages.setdefault(chain_id, set()).add(stage)
    missing_stage_counts: Counter[str] = Counter()
    incomplete_chain_ids: list[str] = []
    for chain_id, observed_stages in sorted(chain_stages.items()):
        missing_stages = EXPECTED_RUNTIME_STAGES - observed_stages
        if missing_stages:
            incomplete_chain_ids.append(chain_id)
            missing_stage_counts.update(missing_stages)
    return {
        "event_count": sum(stages.values()),
        "internal_request_id_count": len(request_ids),
        "request_chain_count": len(chain_stages),
        "complete_chain_count": len(chain_stages) - len(incomplete_chain_ids),
        "incomplete_chain_count": len(incomplete_chain_ids),
        "missing_stage_counts": dict(sorted(missing_stage_counts.items())),
        "incomplete_chain_sample": incomplete_chain_ids[:5],
        "stage_counts": dict(sorted(stages.items())),
        "observer_counts": dict(sorted(observers.items())),
    }


def _source_repo(metadata: dict[str, Any]) -> dict[str, Any]:
    source = metadata.get("parent_repo")
    if isinstance(source, dict):
        return source
    source = metadata.get("repo")
    return source if isinstance(source, dict) else {}


def _mode_command(
    *,
    mode: str,
    result_dir: Path,
    trace_path: Path,
    make_target: str,
) -> list[str]:
    if mode == "hook-enabled":
        return [
            f"VLLM_RLP_TRACE_EXPORT_PATH={trace_path}",
            "make",
            "managed-restart",
            "&&",
            "make",
            make_target,
            f"TRACE_SUITE_OUTPUT_DIR={result_dir}",
        ]
    return [
        "unset",
        "VLLM_RLP_TRACE_EXPORT_PATH",
        "&&",
        "make",
        "managed-restart",
        "&&",
        "make",
        make_target,
        f"TRACE_SUITE_OUTPUT_DIR={result_dir}",
    ]


def _mode_row(
    *,
    mode: str,
    result_dir: Path,
    trace_path: Path,
    make_target: str,
) -> dict[str, Any]:
    summary = _load_json(result_dir / "summary.json")
    metadata = _load_json(result_dir / "run_metadata.json")
    if summary is None or metadata is None:
        return {
            "mode": mode,
            "result_dir": str(result_dir),
            "status": "missing-result",
            "required_next_run": _mode_command(
                mode=mode,
                result_dir=result_dir,
                trace_path=trace_path,
                make_target=make_target,
            ),
        }
    source_repo = _source_repo(metadata)
    trace_summary = _trace_summary(trace_path) if mode == "hook-enabled" else None
    return {
        "mode": mode,
        "result_dir": str(result_dir),
        "status": "loaded",
        "source_evidence_label": metadata.get("evidence_label"),
        "source_commit": source_repo.get("commit"),
        "source_dirty_excluding_output_dir": source_repo.get(
            "dirty_excluding_output_dir"
        ),
        "request_count": summary.get("request_count"),
        "success_count": summary.get("success_count"),
        "error_count": summary.get("error_count"),
        "event_count": summary.get("event_count"),
        "ttft_p50_ms": _metric(summary, "first_token_ms", "p50"),
        "ttft_p95_ms": _metric(summary, "first_token_ms", "p95"),
        "latency_p50_ms": _metric(summary, "latency_ms", "p50"),
        "latency_p95_ms": _metric(summary, "latency_ms", "p95"),
        "trace_export_path": str(trace_path),
        "trace_bytes": _trace_bytes(trace_path) if mode == "hook-enabled" else None,
        "runtime_trace_summary": trace_summary,
        "source_command": metadata.get("command"),
    }


def _delta(
    rows: list[dict[str, Any]], *, key: str
) -> float | int | None:
    by_mode = {row["mode"]: row for row in rows if row["status"] == "loaded"}
    disabled = by_mode.get("hook-disabled", {}).get(key)
    enabled = by_mode.get("hook-enabled", {}).get(key)
    if disabled is None or enabled is None:
        return None
    return enabled - disabled


def build_plan(args: argparse.Namespace) -> dict[str, Any]:
    rows = [
        _mode_row(
            mode="hook-disabled",
            result_dir=args.hook_disabled_dir,
            trace_path=args.trace_export_path,
            make_target=args.make_target,
        ),
        _mode_row(
            mode="hook-enabled",
            result_dir=args.hook_enabled_dir,
            trace_path=args.trace_export_path,
            make_target=args.make_target,
        ),
    ]
    loaded_rows = [row for row in rows if row["status"] == "loaded"]
    missing_rows = [row for row in rows if row["status"] != "loaded"]
    deltas = {
        "ttft_p50_delta_ms": _delta(rows, key="ttft_p50_ms"),
        "ttft_p95_delta_ms": _delta(rows, key="ttft_p95_ms"),
        "latency_p50_delta_ms": _delta(rows, key="latency_p50_ms"),
        "latency_p95_delta_ms": _delta(rows, key="latency_p95_ms"),
        "event_count_delta": _delta(rows, key="event_count"),
    }
    return {
        "metadata": {
            "evidence_label": "derived-artifact",
            "result_valid_for_speedup_claims": False,
            "claim_boundary": (
                "Runtime-hook pair plan and aggregator. This artifact lists the "
                "required hook-disabled and hook-enabled NPU6 runs, then compares "
                "their summaries when present. It is not internal runtime-hook "
                "evidence until both source rows come from clean online runs "
                "launched from the pinned vLLM-HUST submodule."
            ),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "command": [Path(sys.argv[0]).name, *sys.argv[1:]],
            "make_target": args.make_target,
            "trace_export_path": str(args.trace_export_path),
            "loaded_result_count": len(loaded_rows),
            "missing_result_count": len(missing_rows),
            "parent_repo": {
                "path": str(REPO_ROOT),
                "branch": _git_text(["branch", "--show-current"]),
                "commit": _git_text(["rev-parse", "HEAD"]),
                "dirty": _git_dirty(REPO_ROOT),
            },
            "runtime_carrier": {
                "path": str(REPO_ROOT / "third_party" / "vllm-hust"),
                "branch": _git_text(
                    ["branch", "--show-current"],
                    cwd=REPO_ROOT / "third_party" / "vllm-hust",
                ),
                "commit": _git_text(
                    ["rev-parse", "HEAD"],
                    cwd=REPO_ROOT / "third_party" / "vllm-hust",
                ),
                "dirty": _git_dirty(REPO_ROOT / "third_party" / "vllm-hust"),
            },
        },
        "summary": {
            "rows": rows,
            "deltas": deltas,
            "loaded_result_count": len(loaded_rows),
            "missing_result_count": len(missing_rows),
        },
        "rows": rows,
    }


def write_outputs(args: argparse.Namespace, result: dict[str, Any]) -> None:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "run_metadata.json").write_text(
        json.dumps(result["metadata"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "runtime_hook_pair_plan.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "summary.json").write_text(
        json.dumps(result["summary"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plan or aggregate paired NPU6 runtime-hook probes."
    )
    parser.add_argument("--hook-disabled-dir", type=Path, default=DEFAULT_DISABLED_DIR)
    parser.add_argument("--hook-enabled-dir", type=Path, default=DEFAULT_ENABLED_DIR)
    parser.add_argument("--trace-export-path", type=Path, default=DEFAULT_TRACE_PATH)
    parser.add_argument(
        "--make-target",
        default="npu6-existing-server-trace-suite-smoke",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT
        / ".benchmarks"
        / "results"
        / "npu6_runtime_hook_pair_plan",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = build_plan(args)
    write_outputs(args, result)
    print(json.dumps(result["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
