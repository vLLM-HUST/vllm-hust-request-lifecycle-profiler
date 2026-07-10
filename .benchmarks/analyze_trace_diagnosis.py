from __future__ import annotations

import argparse
from collections import Counter
from collections import defaultdict
from datetime import datetime
from datetime import timezone
import csv
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from vllm_request_lifecycle_profiler.trace import LifecycleStage
from vllm_request_lifecycle_profiler.trace import TraceEvent
from vllm_request_lifecycle_profiler.trace import attribute_bottleneck
from vllm_request_lifecycle_profiler.trace import compute_spans
from vllm_request_lifecycle_profiler.trace import evaluate_schema_coverage


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = (
    REPO_ROOT
    / ".benchmarks"
    / "results"
    / "npu6_existing_server_trace_probe_repeated_smoke"
    / "probe_results.json"
)
DEFAULT_OUTPUT_DIR = REPO_ROOT / ".benchmarks" / "results" / "npu6_trace_diagnosis"


def _git(args: list[str], *, cwd: Path = REPO_ROOT) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=cwd, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _git_dirty(cwd: Path) -> bool | str:
    status = _git(["status", "--short"], cwd=cwd)
    if status == "unknown":
        return "unknown"
    return bool(status)


def _git_dirty_excluding(cwd: Path, excluded: Path) -> bool | str:
    try:
        excluded_rel = excluded.resolve().relative_to(cwd.resolve())
    except ValueError:
        return _git_dirty(cwd)
    try:
        status = subprocess.check_output(
            ["git", "status", "--short", "--", ".", f":(exclude){excluded_rel}"],
            cwd=cwd,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return bool(status)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percentile
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _summary(values: list[float]) -> dict[str, float | int | None]:
    return {
        "count": len(values),
        "min": min(values) if values else None,
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "p99": _percentile(values, 0.99),
        "max": max(values) if values else None,
    }


def _load_events(path: Path) -> list[TraceEvent]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    events = payload.get("events", [])
    parsed: list[TraceEvent] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        parsed.append(
            TraceEvent(
                request_id=str(event["request_id"]),
                stage=LifecycleStage(str(event["stage"])),
                timestamp_ms=float(event["timestamp_ms"]),
                metadata=dict(event.get("metadata") or {}),
            )
        )
    return parsed


def analyze_events(events: list[TraceEvent]) -> dict[str, Any]:
    by_request: dict[str, list[TraceEvent]] = defaultdict(list)
    for event in events:
        by_request[event.request_id].append(event)

    rows: list[dict[str, Any]] = []
    span_values: dict[str, list[float]] = defaultdict(list)
    missing_event_rates: list[float] = []
    for request_id, request_events in sorted(by_request.items()):
        phase = "warmup" if "::warmup::" in request_id else "measured"
        coverage = evaluate_schema_coverage(request_events)
        spans = compute_spans(request_events)
        attribution = attribute_bottleneck(request_events, min_duration_ms=0.0)
        span_map = {span.name: span.duration_ms for span in spans}
        for span in spans:
            span_values[span.name].append(span.duration_ms)
        missing_event_rates.append(coverage.missing_event_rate)
        rows.append(
            {
                "request_id": request_id,
                "phase": phase,
                "dominant_kind": attribution.kind.value,
                "dominant_span": attribution.span_name,
                "dominant_duration_ms": attribution.duration_ms,
                "missing_event_rate": coverage.missing_event_rate,
                "complete_span_count": len(coverage.complete_span_names),
                "missing_span_count": len(coverage.missing_span_names),
                **{f"{name}_ms": duration for name, duration in span_map.items()},
            }
        )

    measured = [row for row in rows if row["phase"] == "measured"]
    dominant_counts = Counter(row["dominant_kind"] for row in measured)
    span_summary = {
        name: _summary(values) for name, values in sorted(span_values.items())
    }
    measured_span_summary: dict[str, dict[str, float | int | None]] = {}
    for name in span_values:
        measured_values = [
            float(row[f"{name}_ms"])
            for row in measured
            if row.get(f"{name}_ms") is not None
        ]
        measured_span_summary[name] = _summary(measured_values)

    return {
        "summary": {
            "request_count": len(rows),
            "measured_request_count": len(measured),
            "event_count": len(events),
            "dominant_bottleneck_counts": dict(dominant_counts),
            "dominant_bottleneck": dominant_counts.most_common(1)[0][0]
            if dominant_counts
            else None,
            "missing_event_rate": _summary(missing_event_rates),
            "span_duration_ms": span_summary,
            "measured_span_duration_ms": measured_span_summary,
            "claim_boundary": (
                "Derived diagnosis from client-observed lifecycle proxy events. "
                "This identifies dominant client-visible spans, not internal vLLM "
                "scheduler, KV, prefill, or decode root cause."
            ),
        },
        "rows": rows,
    }


def write_outputs(args: argparse.Namespace, result: dict[str, Any]) -> None:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "evidence_label": "derived-artifact",
        "result_valid_for_speedup_claims": False,
        "claim_boundary": result["summary"]["claim_boundary"],
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "command": [Path(sys.argv[0]).name, *sys.argv[1:]],
        "input_probe_results": str(args.input_probe_results),
        "repo": {
            "path": str(REPO_ROOT),
            "branch": _git(["branch", "--show-current"]),
            "commit": _git(["rev-parse", "HEAD"]),
            "dirty": _git_dirty(REPO_ROOT),
            "dirty_excluding_output_dir": _git_dirty_excluding(
                REPO_ROOT, args.output_dir
            ),
            "dirty_exclusion_dir": str(args.output_dir),
        },
    }
    (args.output_dir / "run_metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "diagnosis.json").write_text(
        json.dumps({**result, "metadata": metadata}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "summary.json").write_text(
        json.dumps(result["summary"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    fieldnames = [
        "request_id",
        "phase",
        "dominant_kind",
        "dominant_span",
        "dominant_duration_ms",
        "missing_event_rate",
        "complete_span_count",
        "missing_span_count",
        "tokenization_ms",
        "queueing_ms",
        "prefill_ms",
        "decode_ms",
        "streaming_ms",
        "cleanup_ms",
    ]
    with (args.output_dir / "request_diagnosis.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in result["rows"]:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Derive client-visible lifecycle diagnosis from NPU6 probe traces."
    )
    parser.add_argument("--input-probe-results", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    events = _load_events(args.input_probe_results)
    result = analyze_events(events)
    write_outputs(args, result)
    print(
        json.dumps(
            {"output_dir": str(args.output_dir), **result["summary"]}, sort_keys=True
        )
    )


if __name__ == "__main__":
    main()
