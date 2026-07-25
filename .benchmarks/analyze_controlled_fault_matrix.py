from __future__ import annotations

import argparse
import csv
from datetime import datetime
from datetime import timezone
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT / ".benchmarks" / "results" / "npu6_controlled_fault_matrix"
)

FAULT_CASES = (
    {
        "case_id": "slow_stream_backpressure",
        "expected_bottleneck": "streaming",
        "fault_ground_truth": {
            "source": "probe_client",
            "injection": "per_chunk_read_delay_ms=80",
            "known_fault_layer": "client_stream_reader",
        },
        "probe_dir": ".benchmarks/results/npu6_runtime_hooks_slow_stream_fault_smoke",
        "diagnosis_dir": ".benchmarks/results/npu6_runtime_hooks_slow_stream_fault_diagnosis",
        "runtime_trace_summary": ".benchmarks/results/npu6_runtime_hooks_slow_stream_fault_smoke/runtime_trace_summary.json",
    },
    {
        "case_id": "structured_decode_heavy",
        "expected_bottleneck": "decode",
        "fault_ground_truth": {
            "source": "workload_shape",
            "injection": "structured-agent decode workload with request_max_tokens=128",
            "known_fault_layer": "decode_visible_output_length",
        },
        "probe_dir": ".benchmarks/results/npu6_runtime_hooks_structured_decode_fault_smoke",
        "diagnosis_dir": ".benchmarks/results/npu6_runtime_hooks_structured_decode_fault_diagnosis",
        "runtime_trace_summary": ".benchmarks/results/npu6_runtime_hooks_structured_decode_fault_smoke/runtime_trace_summary.json",
    },
    {
        "case_id": "prompt_heavy_low_output",
        "expected_bottleneck": "prefill",
        "fault_ground_truth": {
            "source": "workload_shape",
            "injection": "structured-agent prompt with request_max_tokens=4",
            "known_fault_layer": "prefill_visible_prompt_processing",
        },
        "probe_dir": ".benchmarks/results/npu6_runtime_hooks_prompt_heavy_low_output_smoke",
        "diagnosis_dir": ".benchmarks/results/npu6_runtime_hooks_prompt_heavy_low_output_diagnosis",
        "runtime_trace_summary": ".benchmarks/results/npu6_runtime_hooks_prompt_heavy_low_output_smoke/runtime_trace_summary.json",
    },
    {
        "case_id": "concurrency2_prefill_tail",
        "expected_bottleneck": "prefill",
        "fault_ground_truth": {
            "source": "observed_anomaly",
            "injection": "structured-agent concurrency=2 sweep block",
            "known_fault_layer": "runtime_prefill_tail_unresolved_substage",
        },
        "probe_dir": ".benchmarks/results/npu6_runtime_hooks_concurrency_sweep/concurrency_2",
        "diagnosis_dir": ".benchmarks/results/npu6_runtime_hooks_concurrency_sweep/diagnosis_concurrency_2",
        "runtime_trace_summary": ".benchmarks/results/npu6_runtime_hooks_concurrency_sweep/runtime_trace_summary.json",
        "anomaly_summary": ".benchmarks/results/npu6_runtime_hooks_concurrency_sweep/concurrency_anomaly_analysis/summary.json",
    },
)

MISSING_REAL_ONLINE_CASES = (
    {
        "case_id": "queue_pressure",
        "expected_bottleneck": "queueing",
        "missing_reason": "No benchmark-owned repo-launched queue-pressure fault with ground-truth scheduler admission delay is checked in.",
    },
    {
        "case_id": "kv_pressure",
        "expected_bottleneck": "kv_pressure",
        "missing_reason": "No checked-in live run emits KV allocation/cache-pressure fields or ground-truth KV-pressure injection.",
    },
    {
        "case_id": "cleanup_stall",
        "expected_bottleneck": "cleanup",
        "missing_reason": "No checked-in live cleanup-stall injection or cleanup substage hook is available.",
    },
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


def _rel(path: str) -> Path:
    return REPO_ROOT / path


def _summary_value(summary: dict[str, Any], *keys: str) -> Any:
    current: Any = summary
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _baseline_rows(
    *,
    expected: str,
    observed: str | None,
    missing_event_p95: float | None,
) -> list[dict[str, Any]]:
    simple_correct = observed == expected if observed is not None else False
    return [
        {
            "baseline": "causal_rules_enabled",
            "status": "available",
            "observed_bottleneck": observed,
            "correct": simple_correct,
            "time_to_root_cause_measurement": "scripted_not_human_timed",
            "diagnostic_steps": 1,
            "notes": "Reads derived lifecycle diagnosis summary and per-request spans.",
        },
        {
            "baseline": "simple_stage_timer",
            "status": "available",
            "observed_bottleneck": observed,
            "correct": simple_correct,
            "time_to_root_cause_measurement": "scripted_not_human_timed",
            "diagnostic_steps": 2,
            "notes": "Uses largest client-visible lifecycle span; current positive cases do not yet require KV-specific causal rules.",
        },
        {
            "baseline": "causal_rules_disabled",
            "status": "available",
            "observed_bottleneck": observed,
            "correct": simple_correct,
            "time_to_root_cause_measurement": "scripted_not_human_timed",
            "diagnostic_steps": 2,
            "notes": "Falls back to timer-only dominant span. This is not enough for KV-pressure claims.",
        },
        {
            "baseline": "raw_logs",
            "status": "missing",
            "observed_bottleneck": None,
            "correct": None,
            "time_to_root_cause_measurement": "not_measured",
            "diagnostic_steps": None,
            "notes": "No raw vLLM/vLLM-HUST log bundle is checked in for this matrix.",
        },
        {
            "baseline": "manual_posthoc",
            "status": "missing",
            "observed_bottleneck": None,
            "correct": None,
            "time_to_root_cause_measurement": "not_measured",
            "diagnostic_steps": None,
            "notes": "No timed human/manual diagnosis protocol has been run.",
        },
        {
            "baseline": "event_coverage",
            "status": "available",
            "observed_bottleneck": "complete" if missing_event_p95 == 0 else "incomplete",
            "correct": missing_event_p95 == 0,
            "time_to_root_cause_measurement": "not_applicable",
            "diagnostic_steps": 1,
            "notes": "Reports missing-event p95 from derived diagnosis.",
        },
    ]


def _case_row(case: dict[str, Any]) -> dict[str, Any]:
    probe_dir = _rel(str(case["probe_dir"]))
    diagnosis_dir = _rel(str(case["diagnosis_dir"]))
    runtime_trace_summary_path = _rel(str(case["runtime_trace_summary"]))
    diagnosis = _load_json(diagnosis_dir / "summary.json")
    probe_summary = _load_json(probe_dir / "summary.json")
    probe_metadata = _load_json(probe_dir / "run_metadata.json")
    runtime_trace_summary = (
        _load_json(runtime_trace_summary_path)
        if runtime_trace_summary_path.exists()
        else None
    )
    anomaly = None
    if case.get("anomaly_summary"):
        anomaly = _load_json(_rel(str(case["anomaly_summary"])))

    observed = diagnosis.get("dominant_bottleneck")
    expected = str(case["expected_bottleneck"])
    missing_p95 = _summary_value(diagnosis, "missing_event_rate", "p95")
    runtime_complete = (
        _summary_value(runtime_trace_summary or {}, "complete_chain_count")
        if runtime_trace_summary
        else None
    )
    runtime_total = (
        _summary_value(runtime_trace_summary or {}, "request_chain_count")
        if runtime_trace_summary
        else None
    )
    row = {
        "case_id": case["case_id"],
        "status": "available",
        "evidence_label": "derived-artifact over existing-server-probe",
        "result_valid_for_speedup_claims": False,
        "result_valid_for_internal_only_accuracy_claims": False,
        "expected_bottleneck": expected,
        "observed_bottleneck": observed,
        "causal_rules_enabled_correct": observed == expected,
        "measured_request_count": diagnosis.get("measured_request_count"),
        "probe_success_count": probe_summary.get("success_count"),
        "probe_error_count": probe_summary.get("error_count"),
        "missing_event_rate_p95": missing_p95,
        "runtime_complete_chain_count": runtime_complete,
        "runtime_request_chain_count": runtime_total,
        "runtime_missing_stage_counts": (runtime_trace_summary or {}).get(
            "missing_stage_counts"
        ),
        "ttft_p95_ms": _summary_value(probe_summary, "first_token_ms", "p95"),
        "latency_p95_ms": _summary_value(probe_summary, "latency_ms", "p95"),
        "ground_truth": case["fault_ground_truth"],
        "probe_dir": str(probe_dir.relative_to(REPO_ROOT)),
        "diagnosis_dir": str(diagnosis_dir.relative_to(REPO_ROOT)),
        "runtime_trace_summary": str(runtime_trace_summary_path.relative_to(REPO_ROOT)),
        "source_parent_commit": _summary_value(probe_metadata, "repo", "commit"),
        "source_dirty_excluding_output_dir": _summary_value(
            probe_metadata, "repo", "dirty_excluding_output_dir"
        ),
        "baseline_comparison": _baseline_rows(
            expected=expected,
            observed=observed,
            missing_event_p95=missing_p95,
        ),
    }
    if anomaly:
        row["tail_root_cause_status"] = _summary_value(
            anomaly, "diagnosis", "root_cause_status"
        )
        row["tail_stage_localization"] = _summary_value(
            anomaly, "diagnosis", "stage_localization"
        )
        row["required_subprefill_instrumentation"] = anomaly.get(
            "required_subprefill_instrumentation"
        )
        row["prefill_outlier_count"] = anomaly.get("prefill_outlier_count")
        row["prefill_outlier_concurrency_values"] = anomaly.get(
            "prefill_outlier_concurrency_values"
        )
    return row


def build_matrix() -> dict[str, Any]:
    rows = [_case_row(case) for case in FAULT_CASES]
    missing_rows = [
        {
            **case,
            "status": "missing_real_online_ground_truth",
            "evidence_label": None,
            "observed_bottleneck": None,
            "causal_rules_enabled_correct": None,
        }
        for case in MISSING_REAL_ONLINE_CASES
    ]
    available = [row for row in rows if row["status"] == "available"]
    correct = [row for row in available if row["causal_rules_enabled_correct"]]
    false_positive = [
        row
        for row in available
        if row["observed_bottleneck"] is not None
        and row["observed_bottleneck"] != row["expected_bottleneck"]
    ]
    false_negative = [
        row for row in available if row["observed_bottleneck"] in {None, "unknown"}
    ]
    missing_event_p95_values = [
        float(row["missing_event_rate_p95"])
        for row in available
        if row["missing_event_rate_p95"] is not None
    ]
    return {
        "summary": {
            "evidence_label": "derived-artifact",
            "source_evidence_labels": ["existing-server-probe", "derived-artifact"],
            "claim_boundary": (
                "Benchmark-owned aggregation over checked-in NPU6 existing-server "
                "probe and diagnosis artifacts. It is not a repo-launched "
                "real-online controlled-fault matrix and must not be used as "
                "internal-only diagnosis accuracy."
            ),
            "available_case_count": len(available),
            "required_case_count": len(FAULT_CASES) + len(MISSING_REAL_ONLINE_CASES),
            "missing_real_online_case_count": len(missing_rows),
            "causal_rules_enabled_accuracy_available_cases": (
                len(correct) / len(available) if available else 0.0
            ),
            "false_positive_count_available_cases": len(false_positive),
            "false_negative_count_available_cases": len(false_negative),
            "missing_event_rate_p95_max_available_cases": (
                max(missing_event_p95_values) if missing_event_p95_values else None
            ),
            "raw_log_baseline_status": "missing",
            "manual_time_to_root_cause_status": "not_measured",
            "real_online_matrix_status": "incomplete",
            "missing_classes": [row["case_id"] for row in missing_rows],
        },
        "ground_truth": [row["ground_truth"] | {"case_id": row["case_id"]} for row in rows],
        "rows": rows,
        "missing_rows": missing_rows,
    }


def _metadata(args: argparse.Namespace, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "evidence_label": "derived-artifact",
        "result_valid_for_speedup_claims": False,
        "result_valid_for_real_online_accuracy_claims": False,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "command": [Path(sys.argv[0]).name, *sys.argv[1:]],
        "claim_boundary": result["summary"]["claim_boundary"],
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


def write_outputs(args: argparse.Namespace, result: dict[str, Any]) -> None:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    metadata = _metadata(args, result)
    (args.output_dir / "run_metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "ground_truth.json").write_text(
        json.dumps(result["ground_truth"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "matrix.json").write_text(
        json.dumps({**result, "metadata": metadata}, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "summary.json").write_text(
        json.dumps(result["summary"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with (args.output_dir / "fault_matrix.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        fieldnames = [
            "case_id",
            "status",
            "expected_bottleneck",
            "observed_bottleneck",
            "causal_rules_enabled_correct",
            "measured_request_count",
            "missing_event_rate_p95",
            "ttft_p95_ms",
            "latency_p95_ms",
            "runtime_complete_chain_count",
            "runtime_request_chain_count",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in [*result["rows"], *result["missing_rows"]]:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
    lines = [
        "# NPU6 Controlled Fault Matrix",
        "",
        "Evidence label: `derived-artifact`.",
        "",
        result["summary"]["claim_boundary"],
        "",
        "| Case | Status | Expected | Observed | Correct | Missing-event p95 | Runtime chains |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in result["rows"]:
        lines.append(
            "| {case_id} | {status} | {expected} | {observed} | {correct} | {missing} | {chains}/{total} |".format(
                case_id=row["case_id"],
                status=row["status"],
                expected=row["expected_bottleneck"],
                observed=row["observed_bottleneck"],
                correct=row["causal_rules_enabled_correct"],
                missing=row["missing_event_rate_p95"],
                chains=row["runtime_complete_chain_count"],
                total=row["runtime_request_chain_count"],
            )
        )
    for row in result["missing_rows"]:
        lines.append(
            f"| {row['case_id']} | {row['status']} | {row['expected_bottleneck']} |  |  |  |  |"
        )
    lines.extend(
        [
            "",
            "## Missing ASPLOS Gate Items",
            "",
            "- This is not a benchmark-owned repo-launched `real-online` matrix.",
            "- Queue pressure, KV pressure, and cleanup stall live faults are missing.",
            "- Raw-log and timed manual diagnosis baselines are not checked in.",
            "- TPOT, CPU, host-memory, and NPU HBM overhead are not measured by this matrix.",
        ]
    )
    (args.output_dir / "matrix.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Aggregate checked-in NPU6 controlled-fault diagnosis artifacts."
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = build_matrix()
    write_outputs(args, result)
    print(json.dumps(result["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
