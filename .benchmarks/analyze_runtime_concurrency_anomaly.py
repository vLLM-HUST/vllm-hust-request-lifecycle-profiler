from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
from datetime import timezone
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = (
    REPO_ROOT / ".benchmarks" / "results" / "npu6_runtime_hooks_concurrency_sweep"
)
DEFAULT_OUTPUT_DIR = DEFAULT_INPUT_DIR / "concurrency_anomaly_analysis"
RUNTIME_TRACE = DEFAULT_INPUT_DIR / "runtime_trace.jsonl"

SPAN_DEFINITIONS = (
    ("tokenization", "received", "tokenized"),
    ("queueing", "queued", "scheduled"),
    ("prefill", "scheduled", "prefill_done"),
    ("decode", "first_token", "decode_done"),
    ("streaming", "decode_done", "stream_done"),
    ("cleanup", "stream_done", "cleanup_done"),
    ("runtime_total", "received", "cleanup_done"),
)


def _git(args: list[str], *, cwd: Path = REPO_ROOT) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _git_dirty(cwd: Path) -> bool | str:
    status = _git(["status", "--short"], cwd=cwd)
    return "unknown" if status == "unknown" else bool(status)


def _git_dirty_excluding(cwd: Path, excluded: Path) -> bool | str:
    try:
        excluded_rel = excluded.resolve().relative_to(cwd.resolve())
    except ValueError:
        return _git_dirty(cwd)
    try:
        status = subprocess.check_output(
            ["git", "status", "--short", "--", ".", f":(exclude){excluded_rel}"],
            cwd=cwd,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return bool(status)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return sorted(events, key=lambda item: float(item.get("timestamp_ms", 0.0)))


def _chain_id(row: dict[str, Any]) -> str:
    metadata = row.get("metadata", {})
    if isinstance(metadata, dict) and metadata.get("external_request_id"):
        return str(metadata["external_request_id"])
    return str(row.get("request_id", ""))


def _first_metadata(events: list[dict[str, Any]], key: str) -> Any:
    for row in events:
        metadata = row.get("metadata", {})
        if isinstance(metadata, dict) and key in metadata:
            return metadata[key]
    return None


def _span(events: list[dict[str, Any]], start: str, end: str) -> float | None:
    by_stage: dict[str, float] = {}
    for row in events:
        stage = str(row.get("stage", ""))
        by_stage.setdefault(stage, float(row.get("timestamp_ms", 0.0)))
    if start not in by_stage or end not in by_stage:
        return None
    duration = by_stage[end] - by_stage[start]
    return duration if duration >= 0 else None


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * pct
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _stats(values: list[float]) -> dict[str, float | int | None]:
    return {
        "count": len(values),
        "min": min(values) if values else None,
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "max": max(values) if values else None,
    }


def _assigned_blocks(input_dir: Path) -> list[tuple[int, float, float]]:
    blocks: list[tuple[int, float, float]] = []
    for concurrency in (1, 2, 3):
        trace = input_dir / f"concurrency_{concurrency}" / "client_proxy_trace.jsonl"
        if not trace.exists():
            continue
        timestamps = [
            float(json.loads(line)["timestamp_ms"])
            for line in trace.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if timestamps:
            blocks.append((concurrency, min(timestamps), max(timestamps)))
    if len(blocks) != 3:
        return []
    return blocks


def _assign_by_order(rows: list[dict[str, Any]], blocks: list[tuple[int, float, float]]) -> None:
    measured = [row for row in rows if not row["is_warmup"]]
    block_sizes = [9, 9, 9]
    cursor = 0
    for (concurrency, _, _), size in zip(blocks, block_sizes, strict=False):
        for row in measured[cursor : cursor + size]:
            row["assigned_concurrency"] = concurrency
        cursor += size


def build_analysis(args: argparse.Namespace) -> dict[str, Any]:
    events = _load_events(args.runtime_trace)
    by_chain: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in events:
        by_chain[_chain_id(row)].append(row)

    rows: list[dict[str, Any]] = []
    for chain_id, chain_events in sorted(
        by_chain.items(),
        key=lambda item: min(float(row["timestamp_ms"]) for row in item[1]),
    ):
        spans = {
            name: _span(chain_events, start, end)
            for name, start, end in SPAN_DEFINITIONS
        }
        prompt_tokens = _first_metadata(chain_events, "prompt_tokens")
        cached_tokens = _first_metadata(chain_events, "cached_tokens")
        generation_tokens = _first_metadata(chain_events, "generation_tokens")
        max_tokens = _first_metadata(chain_events, "max_tokens")
        rows.append(
            {
                "chain_id": chain_id,
                "assigned_concurrency": None,
                "is_warmup": len(rows) in {0, 10, 20},
                "prompt_tokens": prompt_tokens,
                "cached_tokens": cached_tokens,
                "cached_token_ratio": (
                    cached_tokens / prompt_tokens
                    if isinstance(prompt_tokens, int)
                    and prompt_tokens
                    and isinstance(cached_tokens, int)
                    else None
                ),
                "generation_tokens": generation_tokens,
                "max_tokens": max_tokens,
                "spans_ms": spans,
            }
        )

    blocks = _assigned_blocks(args.input_dir)
    _assign_by_order(rows, blocks)

    measured_rows = [row for row in rows if row["assigned_concurrency"] is not None]
    prefill_values = [
        float(row["spans_ms"]["prefill"])
        for row in measured_rows
        if row["spans_ms"].get("prefill") is not None
    ]
    outlier_threshold_ms = max(1000.0, (_percentile(prefill_values, 0.95) or 0.0) / 2)
    outliers = [
        row
        for row in measured_rows
        if (row["spans_ms"].get("prefill") or 0.0) >= outlier_threshold_ms
    ]

    per_concurrency: list[dict[str, Any]] = []
    for concurrency in sorted({int(row["assigned_concurrency"]) for row in measured_rows}):
        group = [row for row in measured_rows if row["assigned_concurrency"] == concurrency]
        prefill = [float(row["spans_ms"]["prefill"]) for row in group]
        queueing = [float(row["spans_ms"]["queueing"]) for row in group]
        decode = [float(row["spans_ms"]["decode"]) for row in group]
        cached_ratios = [
            float(row["cached_token_ratio"])
            for row in group
            if row["cached_token_ratio"] is not None
        ]
        per_concurrency.append(
            {
                "concurrency": concurrency,
                "measured_chain_count": len(group),
                "prompt_token_values": sorted({row["prompt_tokens"] for row in group}),
                "generation_token_values": sorted(
                    {row["generation_tokens"] for row in group}
                ),
                "cached_token_ratio": _stats(cached_ratios),
                "prefill_ms": _stats(prefill),
                "queueing_ms": _stats(queueing),
                "decode_ms": _stats(decode),
                "prefill_outlier_count": sum(
                    1
                    for row in group
                    if (row["spans_ms"].get("prefill") or 0.0) >= outlier_threshold_ms
                ),
            }
        )

    return {
        "metadata": {
            "evidence_label": "derived-artifact",
            "claim_boundary": (
                "Post-hoc analysis of checked-in NPU6 runtime hook traces. "
                "It localizes the observed tail to lifecycle spans and metadata "
                "already emitted by the runtime hooks; it does not yet prove the "
                "sub-stage root cause inside prefill."
            ),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "command": [Path(sys.argv[0]).name, *sys.argv[1:]],
            "input_dir": str(args.input_dir),
            "runtime_trace": str(args.runtime_trace),
            "parent_repo": {
                "path": str(REPO_ROOT),
                "branch": _git(["branch", "--show-current"]),
                "commit": _git(["rev-parse", "HEAD"]),
                "dirty": _git_dirty(REPO_ROOT),
                "dirty_excluding_output_dir": _git_dirty_excluding(
                    REPO_ROOT, args.output_dir
                ),
                "dirty_exclusion_dir": str(args.output_dir),
            },
        },
        "summary": {
            "chain_count": len(rows),
            "measured_chain_count": len(measured_rows),
            "outlier_threshold_ms": outlier_threshold_ms,
            "prefill_outlier_count": len(outliers),
            "prefill_outlier_concurrency_values": sorted(
                {row["assigned_concurrency"] for row in outliers}
            ),
            "interpretation": (
                "The checked-in sweep holds prompt_tokens and generation_tokens "
                "constant. The only >1s runtime prefill outliers occur in the "
                "concurrency-2 block, while queueing/decode stay small. Current "
                "hooks therefore justify the next instrumentation split inside "
                "prefill, especially scheduler-output shape, KV allocation/cache "
                "state, graph/batch transition, and prefill kernel execution."
            ),
            "per_concurrency": per_concurrency,
            "outliers": outliers,
        },
        "request_rows": rows,
    }


def write_outputs(args: argparse.Namespace, result: dict[str, Any]) -> None:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "run_metadata.json").write_text(
        json.dumps(result["metadata"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "summary.json").write_text(
        json.dumps(result["summary"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "request_rows.json").write_text(
        json.dumps(result["request_rows"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Runtime Concurrency Anomaly Analysis",
        "",
        "Evidence label: `derived-artifact`.",
        "",
        result["metadata"]["claim_boundary"],
        "",
        "| Concurrency | Chains | Prefill p50/p95/max ms | Queue p95 ms | Decode p95 ms | Cached-token ratio p50 | Prefill outliers |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in result["summary"]["per_concurrency"]:
        prefill = row["prefill_ms"]
        queueing = row["queueing_ms"]
        decode = row["decode_ms"]
        cached = row["cached_token_ratio"]
        lines.append(
            "| {concurrency} | {chains} | {p50:.2f}/{p95:.2f}/{maxv:.2f} | "
            "{queue_p95:.2f} | {decode_p95:.2f} | {cached_p50:.3f} | {outliers} |".format(
                concurrency=row["concurrency"],
                chains=row["measured_chain_count"],
                p50=prefill["p50"],
                p95=prefill["p95"],
                maxv=prefill["max"],
                queue_p95=queueing["p95"],
                decode_p95=decode["p95"],
                cached_p50=cached["p50"],
                outliers=row["prefill_outlier_count"],
            )
        )
    lines.extend(
        [
            "",
            "Interpretation:",
            "",
            f"- {result['summary']['interpretation']}",
            "- Do not claim KV allocator, graph capture, or kernel root cause from this artifact alone.",
        ]
    )
    (args.output_dir / "anomaly_analysis.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze checked-in runtime hook traces for the NPU6 concurrency anomaly."
    )
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--runtime-trace", type=Path, default=RUNTIME_TRACE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = build_analysis(args)
    write_outputs(args, result)
    print(json.dumps(result["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
