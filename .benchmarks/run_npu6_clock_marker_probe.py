#!/usr/bin/env python3
"""Collect real Ascend clock-marker brackets under an external msprof run."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import torch
import torch_npu  # noqa: F401

from vllm_request_lifecycle_profiler import AscendClockMarkerCollector


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a small NPU6 workload with real Ascend clock markers."
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--marker-count", type=int, default=21)
    parser.add_argument("--logical-device-id", type=int, default=0)
    parser.add_argument("--profiler-device-id", type=int, default=6)
    parser.add_argument("--matrix-size", type=int, default=256)
    parser.add_argument("--spacing-ms", type=float, default=10.0)
    return parser.parse_args()


def _percentile(values: list[int], probability: float) -> int:
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int(len(ordered) * probability + 0.999999)))
    return ordered[rank - 1]


def main() -> int:
    args = _parse_args()
    if args.marker_count < 6:
        raise ValueError("marker-count must be at least 6")
    if args.matrix_size <= 0:
        raise ValueError("matrix-size must be positive")
    if args.spacing_ms < 0:
        raise ValueError("spacing-ms must be non-negative")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    marker_path = args.output_dir / "clock_marker_brackets.tsv"
    if marker_path.exists():
        raise FileExistsError(
            f"refusing to append to existing marker file: {marker_path}"
        )

    torch.npu.set_device(args.logical_device_id)
    left = torch.randn(
        (args.matrix_size, args.matrix_size),
        dtype=torch.float16,
        device="npu",
    )
    right = torch.randn_like(left)
    for _ in range(3):
        torch.mm(left, right)
    torch.npu.synchronize()

    brackets: list[dict[str, Any]] = []
    workload_durations_ns: list[int] = []
    started_ns = time.perf_counter_ns()
    with AscendClockMarkerCollector(
        marker_path,
        device_id=args.profiler_device_id,
        call_site="npu6_clock_marker_probe",
    ) as collector:
        for marker_index in range(args.marker_count):
            bracket = collector.record(f"npu6-real-{marker_index:04d}")
            workload_started_ns = time.perf_counter_ns()
            torch.mm(left, right)
            torch.npu.synchronize()
            workload_durations_ns.append(time.perf_counter_ns() - workload_started_ns)
            brackets.append(
                {
                    "host_after_ns": bracket.host_after_ns,
                    "host_before_ns": bracket.host_before_ns,
                    "record_after_ns": bracket.record_after_ns,
                    "marker_id": bracket.marker_id,
                    "return_status": bracket.return_status,
                }
            )
            if args.spacing_ms:
                time.sleep(args.spacing_ms / 1000.0)
    elapsed_ns = time.perf_counter_ns() - started_ns

    bracket_widths_ns = [
        row["host_after_ns"] - row["host_before_ns"] for row in brackets
    ]
    record_bracket_widths_ns = [
        row["record_after_ns"] - row["host_before_ns"] for row in brackets
    ]
    summary = {
        "artifact_label": "real-online v4.4 calibration-chain smoke",
        "bracket_width_ns": {
            "max": max(bracket_widths_ns),
            "p50": _percentile(bracket_widths_ns, 0.50),
            "p95": _percentile(bracket_widths_ns, 0.95),
        },
        "elapsed_ns": elapsed_ns,
        "logical_device_id": args.logical_device_id,
        "marker_count": len(brackets),
        "marker_path": str(marker_path.resolve()),
        "record_bracket_width_ns": {
            "max": max(record_bracket_widths_ns),
            "p50": _percentile(record_bracket_widths_ns, 0.50),
            "p95": _percentile(record_bracket_widths_ns, 0.95),
        },
        "physical_device_visibility": {
            "ASCEND_RT_VISIBLE_DEVICES": os.environ.get("ASCEND_RT_VISIBLE_DEVICES"),
            "ASCEND_VISIBLE_DEVICES": os.environ.get("ASCEND_VISIBLE_DEVICES"),
        },
        "profiler_device_id": args.profiler_device_id,
        "successful_marker_count": sum(row["return_status"] == 0 for row in brackets),
        "workload_duration_ns": {
            "max": max(workload_durations_ns),
            "p50": _percentile(workload_durations_ns, 0.50),
            "p95": _percentile(workload_durations_ns, 0.95),
        },
    }
    summary_path = args.output_dir / "probe_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
