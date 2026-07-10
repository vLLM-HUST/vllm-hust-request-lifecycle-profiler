from __future__ import annotations

import argparse
import csv
import json
import shutil
from collections import Counter
from pathlib import Path


FIGURE_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".svg", ".webp"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refresh generic paper-facing assets from a paper results directory."
    )
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--live-results-dir")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--figure-dir", required=True)
    parser.add_argument("--table-dir", required=True)
    parser.add_argument("--manifest-json", required=True)
    parser.add_argument("--summary-markdown", required=True)
    parser.add_argument("--summary-tex", required=True)
    return parser.parse_args()


def path_is_within(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
        return True
    except ValueError:
        return False


def iter_result_files(
    results_dir: Path | None,
    *,
    excluded_paths: set[Path],
    excluded_dirs: set[Path],
    excluded_relative_dirs: set[Path],
) -> list[Path]:
    if results_dir is None or not results_dir.exists():
        return []
    return sorted(
        path
        for path in results_dir.rglob("*")
        if path.is_file()
        and path.resolve() not in excluded_paths
        and not any(
            path_is_within(path.resolve(), excluded_dir)
            for excluded_dir in excluded_dirs
        )
        and not any(
            path_is_within(path.relative_to(results_dir), excluded_relative_dir)
            for excluded_relative_dir in excluded_relative_dirs
        )
    )


def latex_escape(text: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in text)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_json(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _parent_commit(metadata: dict[str, object]) -> object:
    repo = metadata.get("repo", {})
    if isinstance(repo, dict) and repo.get("commit"):
        return repo["commit"]
    return metadata.get("parent_commit", "unknown")


def _trace_probe_summary(repo_root: Path) -> dict[str, object] | None:
    result_dir_name = "npu6_existing_server_trace_probe_repeated_smoke"
    result_dir = repo_root / ".benchmarks" / "results" / result_dir_name
    summary = _load_json(result_dir / "summary.json")
    metadata = _load_json(result_dir / "run_metadata.json")
    probe = _load_json(result_dir / "probe_results.json")
    if summary is None or metadata is None:
        return None
    stages: list[str] = []
    if probe is not None:
        stages = sorted(
            {
                str(event["stage"])
                for event in probe.get("events", [])
                if isinstance(event, dict) and "stage" in event
            }
        )
    ttft = summary["first_token_ms"]
    latency = summary["latency_ms"]
    return {
        "result_dir": result_dir_name,
        "evidence_label": metadata["evidence_label"],
        "parent_commit": _parent_commit(metadata),
        "workload_commit": metadata["workload_source"]["commit"],
        "trace_boundary": metadata["trace_boundary"],
        "warmup_request_count": summary["warmup_request_count"],
        "warmup_success_count": summary["warmup_success_count"],
        "request_count": summary["request_count"],
        "success_count": summary["success_count"],
        "error_count": summary["error_count"],
        "event_count": summary["event_count"],
        "stage_count": len(stages),
        "stages": ",".join(stages),
        "ttft_p50_ms": ttft["p50"],
        "ttft_p95_ms": ttft["p95"],
        "ttft_p99_ms": ttft["p99"],
        "latency_p50_ms": latency["p50"],
        "latency_p95_ms": latency["p95"],
        "latency_p99_ms": latency["p99"],
    }


def write_trace_probe_summary_csv(path: Path, row: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "request_count",
        "success_count",
        "error_count",
        "warmup_request_count",
        "event_count",
        "stage_count",
        "ttft_p50_ms",
        "ttft_p95_ms",
        "ttft_p99_ms",
        "latency_p50_ms",
        "latency_p95_ms",
        "latency_p99_ms",
        "evidence_label",
        "parent_commit",
        "workload_commit",
        "result_dir",
        "stages",
        "trace_boundary",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow({field: row.get(field, "") for field in fieldnames})


def write_trace_probe_summary_table(path: Path, row: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "% Auto-generated by experiments/export_paper_assets.py. Do not edit by hand.",
        "\\small",
        "\\begin{tabular}{lrrrr}",
        "\\toprule",
        "Run & Req. & Events & TTFT p95 & Lat. p95 \\\\",
        "\\midrule",
        (
            f"Measured & {row['request_count']} & {row['event_count']} & "
            f"{float(row['ttft_p95_ms']):.2f} & {float(row['latency_p95_ms']):.2f} \\\\"
        ),
        "\\bottomrule",
        "\\end{tabular}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_trace_probe_summary_svg(path: Path, row: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 640, 300
    left, top, plot_h = 90, 54, 165
    labels = ["TTFT p50", "TTFT p95", "TTFT p99", "Lat. p95"]
    values = [
        float(row["ttft_p50_ms"]),
        float(row["ttft_p95_ms"]),
        float(row["ttft_p99_ms"]),
        float(row["latency_p95_ms"]),
    ]
    max_v = max(values) * 1.15
    bar_w = 72
    gap = 45

    def y(value: float) -> float:
        return top + plot_h - (value / max_v) * plot_h

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        "<style>text{font-family:Arial,Helvetica,sans-serif;font-size:13px;fill:#111827}.axis{stroke:#374151;stroke-width:1.2}.grid{stroke:#e5e7eb;stroke-width:1}.bar{fill:#2563eb}.meta{fill:#4b5563}</style>",
        f'<text x="{width / 2}" y="24" text-anchor="middle" font-weight="700">Warmup-controlled NPU6 client-observed trace probe</text>',
        f'<line class="axis" x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}"/>',
        f'<line class="axis" x1="{left}" y1="{top + plot_h}" x2="{width - 42}" y2="{top + plot_h}"/>',
        f'<text transform="translate(24,{top + plot_h / 2}) rotate(-90)" text-anchor="middle">Milliseconds</text>',
    ]
    for tick in [0, 50, 100, 150, 200]:
        tick_y = y(float(tick))
        svg.extend(
            [
                f'<line class="grid" x1="{left}" y1="{tick_y:.1f}" x2="{width - 42}" y2="{tick_y:.1f}"/>',
                f'<text x="{left - 8}" y="{tick_y + 4:.1f}" text-anchor="end">{tick}</text>',
            ]
        )
    for index, (label, value) in enumerate(zip(labels, values)):
        x_pos = left + 44 + index * (bar_w + gap)
        bar_y = y(value)
        svg.extend(
            [
                f'<rect class="bar" x="{x_pos}" y="{bar_y:.1f}" width="{bar_w}" height="{top + plot_h - bar_y:.1f}"/>',
                f'<text x="{x_pos + bar_w / 2}" y="{bar_y - 7:.1f}" text-anchor="middle">{value:.1f}</text>',
                f'<text x="{x_pos + bar_w / 2}" y="{top + plot_h + 20}" text-anchor="middle">{label}</text>',
            ]
        )
    svg.append(
        f'<text class="meta" x="{width / 2}" y="{height - 20}" text-anchor="middle">'
        f"{row['request_count']} measured requests, {row['event_count']} lifecycle events, "
        f"{row['error_count']} errors</text>"
    )
    svg.append("</svg>")
    path.write_text("\n".join(svg) + "\n", encoding="utf-8")


def generate_trace_probe_assets(
    *,
    repo_root: Path,
    output_dir: Path,
    figure_dir: Path,
    table_dir: Path,
) -> list[dict[str, object]]:
    row = _trace_probe_summary(repo_root)
    if row is None:
        return []
    csv_path = output_dir / "npu6_trace_probe_summary.csv"
    table_path = table_dir / "npu6_trace_probe_summary.tex"
    figure_path = figure_dir / "npu6_trace_probe_summary.svg"
    write_trace_probe_summary_csv(csv_path, row)
    write_trace_probe_summary_table(table_path, row)
    write_trace_probe_summary_svg(figure_path, row)
    return [
        {
            "kind": "csv",
            "path": csv_path.as_posix(),
            "rows": 1,
            "evidence_label": "derived-artifact",
        },
        {
            "kind": "table",
            "path": table_path.as_posix(),
            "rows": 1,
            "evidence_label": "derived-artifact",
        },
        {
            "kind": "figure",
            "path": figure_path.as_posix(),
            "rows": 1,
            "evidence_label": "derived-artifact",
        },
    ]


def _trace_overhead_rows(repo_root: Path) -> list[dict[str, object]]:
    result_dir_name = "npu6_existing_server_trace_overhead_smoke"
    result_dir = repo_root / ".benchmarks" / "results" / result_dir_name
    overhead = _load_json(result_dir / "overhead_summary.json")
    if overhead is None:
        return []
    comparison = overhead["comparison"]
    rows: list[dict[str, object]] = []
    for row in comparison["modes"]:
        row = dict(row)
        row["result_dir"] = result_dir_name
        rows.append(row)
    deltas = comparison.get("deltas", {})
    for row in rows:
        if row["mode"] == "trace":
            row["ttft_p95_delta_ms_vs_no_trace"] = deltas.get("ttft_p95_delta_ms")
            row["latency_p95_delta_ms_vs_no_trace"] = deltas.get("latency_p95_delta_ms")
        else:
            row["ttft_p95_delta_ms_vs_no_trace"] = 0.0
            row["latency_p95_delta_ms_vs_no_trace"] = 0.0
    return rows


def write_trace_overhead_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "mode",
        "request_count",
        "success_count",
        "error_count",
        "event_count",
        "ttft_p50_ms",
        "ttft_p95_ms",
        "latency_p50_ms",
        "latency_p95_ms",
        "ttft_p95_delta_ms_vs_no_trace",
        "latency_p95_delta_ms_vs_no_trace",
        "result_dir",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def write_trace_overhead_table(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "% Auto-generated by experiments/export_paper_assets.py. Do not edit by hand.",
        "\\small",
        "\\begin{tabular}{lrrrr}",
        "\\toprule",
        "Mode & Req. & Events & TTFT p95 & $\\Delta$TTFT p95 \\\\",
        "\\midrule",
    ]
    for row in rows:
        lines.append(
            f"{latex_escape(str(row['mode']))} & {row['request_count']} & {row['event_count']} & "
            f"{float(row['ttft_p95_ms']):.2f} & {float(row['ttft_p95_delta_ms_vs_no_trace']):.2f} \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate_trace_overhead_assets(
    *,
    repo_root: Path,
    output_dir: Path,
    table_dir: Path,
) -> list[dict[str, object]]:
    rows = _trace_overhead_rows(repo_root)
    if not rows:
        return []
    csv_path = output_dir / "npu6_trace_overhead.csv"
    table_path = table_dir / "npu6_trace_overhead.tex"
    write_trace_overhead_csv(csv_path, rows)
    write_trace_overhead_table(table_path, rows)
    return [
        {
            "kind": "csv",
            "path": csv_path.as_posix(),
            "rows": len(rows),
            "evidence_label": "derived-artifact",
        },
        {
            "kind": "table",
            "path": table_path.as_posix(),
            "rows": len(rows),
            "evidence_label": "derived-artifact",
        },
    ]


def _synthetic_fault_row(repo_root: Path) -> dict[str, object] | None:
    result_dir_name = "synthetic_fault_injection_env"
    result_dir = repo_root / ".benchmarks" / "results" / result_dir_name
    matrix = _load_json(result_dir / "matrix.json")
    metadata = _load_json(result_dir / "run_metadata.json")
    if matrix is None or metadata is None:
        return None
    rows = matrix["rows"]
    scenario_names = [str(row["scenario"]) for row in rows]
    return {
        "result_dir": result_dir_name,
        "evidence_label": metadata["evidence_label"],
        "parent_commit": _parent_commit(metadata),
        "scenario_count": matrix["scenario_count"],
        "correct_count": matrix["correct_count"],
        "accuracy": matrix["accuracy"],
        "false_positive_count": matrix["false_positive_count"],
        "false_negative_count": matrix["false_negative_count"],
        "max_missing_event_rate": max(
            float(row["missing_event_rate"]) for row in rows
        )
        if rows
        else 0.0,
        "scenario_names": ",".join(scenario_names),
    }


def write_synthetic_fault_csv(path: Path, row: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "scenario_count",
        "correct_count",
        "accuracy",
        "false_positive_count",
        "false_negative_count",
        "max_missing_event_rate",
        "evidence_label",
        "parent_commit",
        "result_dir",
        "scenario_names",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow({field: row.get(field, "") for field in fieldnames})


def write_synthetic_fault_table(path: Path, row: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "% Auto-generated by experiments/export_paper_assets.py. Do not edit by hand.",
        "\\small",
        "\\begin{tabular}{lrrrr}",
        "\\toprule",
        "Suite & Cases & Correct & FP/FN & Missing \\\\",
        "\\midrule",
        (
            f"Synthetic faults & {row['scenario_count']} & "
            f"{row['correct_count']}/{row['scenario_count']} & "
            f"{row['false_positive_count']}/{row['false_negative_count']} & "
            f"{float(row['max_missing_event_rate']):.2f} \\\\"
        ),
        "\\bottomrule",
        "\\end{tabular}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate_synthetic_fault_assets(
    *,
    repo_root: Path,
    output_dir: Path,
    table_dir: Path,
) -> list[dict[str, object]]:
    row = _synthetic_fault_row(repo_root)
    if row is None:
        return []
    csv_path = output_dir / "synthetic_fault_injection.csv"
    table_path = table_dir / "synthetic_fault_injection.tex"
    write_synthetic_fault_csv(csv_path, row)
    write_synthetic_fault_table(table_path, row)
    return [
        {
            "kind": "csv",
            "path": csv_path.as_posix(),
            "rows": 1,
            "evidence_label": "derived-artifact",
        },
        {
            "kind": "table",
            "path": table_path.as_posix(),
            "rows": 1,
            "evidence_label": "derived-artifact",
        },
    ]


def _trace_diagnosis_row_for(
    repo_root: Path, *, result_dir_name: str
) -> dict[str, object] | None:
    result_dir = repo_root / ".benchmarks" / "results" / result_dir_name
    summary = _load_json(result_dir / "summary.json")
    metadata = _load_json(result_dir / "run_metadata.json")
    if summary is None or metadata is None:
        return None
    spans = summary["measured_span_duration_ms"]
    dominant_counts = summary["dominant_bottleneck_counts"]
    dominant = str(summary.get("dominant_bottleneck", "unknown"))
    dominant_count = int(dominant_counts.get(dominant, 0))
    return {
        "result_dir": result_dir_name,
        "evidence_label": metadata["evidence_label"],
        "parent_commit": _parent_commit(metadata),
        "measured_request_count": summary["measured_request_count"],
        "event_count": summary["event_count"],
        "dominant_bottleneck": dominant,
        "dominant_count": dominant_count,
        "tokenization_p95_ms": spans["tokenization"]["p95"],
        "queueing_p95_ms": spans["queueing"]["p95"],
        "prefill_p95_ms": spans["prefill"]["p95"],
        "decode_p95_ms": spans["decode"]["p95"],
        "streaming_p95_ms": spans["streaming"]["p95"],
        "cleanup_p95_ms": spans["cleanup"]["p95"],
        "missing_event_rate_p95": summary["missing_event_rate"]["p95"],
        "claim_boundary": summary["claim_boundary"],
    }


def _trace_diagnosis_row(repo_root: Path) -> dict[str, object] | None:
    return _trace_diagnosis_row_for(
        repo_root, result_dir_name="npu6_trace_diagnosis"
    )


def write_trace_diagnosis_csv(path: Path, row: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "measured_request_count",
        "event_count",
        "dominant_bottleneck",
        "dominant_count",
        "tokenization_p95_ms",
        "queueing_p95_ms",
        "prefill_p95_ms",
        "decode_p95_ms",
        "streaming_p95_ms",
        "cleanup_p95_ms",
        "missing_event_rate_p95",
        "evidence_label",
        "parent_commit",
        "result_dir",
        "claim_boundary",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow({field: row.get(field, "") for field in fieldnames})


def write_trace_diagnosis_table(path: Path, row: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    spans = [
        ("Tokenization", "tokenization_p95_ms"),
        ("Queueing", "queueing_p95_ms"),
        ("Prefill-proxy", "prefill_p95_ms"),
        ("Decode-proxy", "decode_p95_ms"),
        ("Streaming", "streaming_p95_ms"),
        ("Cleanup", "cleanup_p95_ms"),
    ]
    lines = [
        "% Auto-generated by experiments/export_paper_assets.py. Do not edit by hand.",
        "\\small",
        "\\begin{tabular}{lrrrr}",
        "\\toprule",
        "Span & p95 ms & Dominant & Events & Missing \\\\",
        "\\midrule",
    ]
    for label, key in spans:
        dominant = (
            f"{row['dominant_count']}/{row['measured_request_count']}"
            if str(row["dominant_bottleneck"]) in label.lower()
            else "-"
        )
        lines.append(
            f"{label} & {float(row[key]):.2f} & {dominant} & "
            f"{row['event_count']} & {float(row['missing_event_rate_p95']):.2f} \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate_trace_diagnosis_assets(
    *,
    repo_root: Path,
    output_dir: Path,
    table_dir: Path,
) -> list[dict[str, object]]:
    row = _trace_diagnosis_row(repo_root)
    if row is None:
        return []
    csv_path = output_dir / "npu6_trace_diagnosis.csv"
    table_path = table_dir / "npu6_trace_diagnosis.tex"
    write_trace_diagnosis_csv(csv_path, row)
    write_trace_diagnosis_table(table_path, row)
    return [
        {
            "kind": "csv",
            "path": csv_path.as_posix(),
            "rows": 1,
            "evidence_label": "derived-artifact",
        },
        {
            "kind": "table",
            "path": table_path.as_posix(),
            "rows": 1,
            "evidence_label": "derived-artifact",
        },
    ]


def _slow_stream_diagnosis_row(repo_root: Path) -> dict[str, object] | None:
    return _trace_diagnosis_row_for(
        repo_root, result_dir_name="npu6_slow_stream_trace_diagnosis"
    )


def write_slow_stream_diagnosis_csv(
    path: Path, row: dict[str, object]
) -> None:
    write_trace_diagnosis_csv(path, row)


def write_slow_stream_diagnosis_table(
    path: Path, row: dict[str, object]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "% Auto-generated by experiments/export_paper_assets.py. Do not edit by hand.",
        "\\small",
        "\\begin{tabular}{lrrrr}",
        "\\toprule",
        "Run & Dominant & Prefill p95 & Streaming p95 & Missing \\\\",
        "\\midrule",
        (
            f"Slow-stream proxy & "
            f"{latex_escape(str(row['dominant_bottleneck']))} "
            f"{row['dominant_count']}/{row['measured_request_count']} & "
            f"{float(row['prefill_p95_ms']):.2f} & "
            f"{float(row['streaming_p95_ms']):.2f} & "
            f"{float(row['missing_event_rate_p95']):.2f} \\\\"
        ),
        "\\bottomrule",
        "\\end{tabular}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate_slow_stream_diagnosis_assets(
    *,
    repo_root: Path,
    output_dir: Path,
    table_dir: Path,
) -> list[dict[str, object]]:
    row = _slow_stream_diagnosis_row(repo_root)
    if row is None:
        return []
    csv_path = output_dir / "npu6_slow_stream_trace_diagnosis.csv"
    table_path = table_dir / "npu6_slow_stream_trace_diagnosis.tex"
    write_slow_stream_diagnosis_csv(csv_path, row)
    write_slow_stream_diagnosis_table(table_path, row)
    return [
        {
            "kind": "csv",
            "path": csv_path.as_posix(),
            "rows": 1,
            "evidence_label": "derived-artifact",
        },
        {
            "kind": "table",
            "path": table_path.as_posix(),
            "rows": 1,
            "evidence_label": "derived-artifact",
        },
    ]


def write_markdown(
    path: Path,
    *,
    total_files: int,
    total_staged_figures: int,
    counts: Counter[str],
    source_counts: dict[str, int],
    files: list[dict[str, object]],
    staged_figures: list[str],
    derived_assets: list[dict[str, object]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Paper Asset Summary",
        "",
        f"- Total result files: {total_files}",
        f"- Staged figures: {total_staged_figures}",
        "",
        "## Files By Source",
        "",
        "| Source | Count |",
        "| --- | ---: |",
    ]
    if source_counts:
        for source_name, count in sorted(source_counts.items()):
            lines.append(f"| `{source_name}` | {count} |")
    else:
        lines.append("| `(none)` | 0 |")

    lines.extend(
        [
            "",
            "## Files By Extension",
            "",
            "| Extension | Count |",
            "| --- | ---: |",
        ]
    )
    if counts:
        for suffix, count in sorted(counts.items()):
            lines.append(f"| `{suffix}` | {count} |")
    else:
        lines.append("| `(none)` | 0 |")

    lines.extend(["", "## Result Files", ""])
    if files:
        for item in files:
            lines.append(
                f"- `{item['source']}/{item['relative_path']}` ({item['size_bytes']} bytes)"
            )
    else:
        lines.append("- No result files found yet.")

    if staged_figures:
        lines.extend(["", "## Staged Figures", ""])
        for relative_path in staged_figures:
            lines.append(f"- `figures/generated/{relative_path}`")

    if derived_assets:
        lines.extend(["", "## Derived Paper Assets", ""])
        for asset in derived_assets:
            lines.append(
                f"- `{asset['path']}` ({asset['kind']}, {asset['evidence_label']})"
            )

    path.write_text("\n".join(lines) + "\n")


def write_tex(
    path: Path,
    *,
    total_files: int,
    counts: Counter[str],
    source_counts: dict[str, int],
    staged_figures: list[str],
    derived_assets: list[dict[str, object]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "% Auto-generated by experiments/export_paper_assets.py. Do not edit by hand.",
        "\\paragraph{Current Result Snapshot}",
        f"The paper workspace currently sees {total_files} result file(s) under \\texttt{{results/}}.",
        "",
    ]

    if counts:
        lines.extend(
            [
                "\\begin{center}",
                "\\begin{tabular}{lr}",
                "\\toprule",
                "Extension & Count \\\\",
                "\\midrule",
            ]
        )
        for suffix, count in sorted(counts.items()):
            lines.append(f"{latex_escape(suffix)} & {count} \\\\")
        lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{center}"])
    else:
        lines.append(
            "No result files have been exported yet, so there are no derived paper assets to summarize."
        )

    if source_counts:
        lines.extend(["", "\\paragraph{Source Breakdown}", "\\begin{itemize}"])
        for source_name, count in sorted(source_counts.items()):
            lines.append(
                f"\\item \\texttt{{{latex_escape(source_name)}}}: {count} file(s)"
            )
        lines.append("\\end{itemize}")

    if staged_figures:
        lines.extend(["", "\\paragraph{Staged Figures}", "\\begin{itemize}"])
        for relative_path in staged_figures:
            lines.append(
                f"\\item \\texttt{{figures/generated/{latex_escape(relative_path)}}}"
            )
        lines.append("\\end{itemize}")

    if derived_assets:
        lines.extend(["", "\\paragraph{Derived Assets}", "\\begin{itemize}"])
        for asset in derived_assets:
            lines.append(
                f"\\item \\texttt{{{latex_escape(str(asset['path']))}}} ({latex_escape(str(asset['kind']))})"
            )
        lines.append("\\end{itemize}")

    path.write_text("\n".join(lines) + "\n")


def stage_figures(
    result_files: list[Path],
    *,
    source_dir: Path,
    source_label: str,
    generated_figures_dir: Path,
) -> list[str]:
    staged: list[str] = []
    for path in result_files:
        if path.suffix.lower() not in FIGURE_SUFFIXES:
            continue
        relative = Path(source_label) / path.relative_to(source_dir)
        destination = generated_figures_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        staged.append(relative.as_posix())
    return staged


def collect_source_files(
    source_name: str,
    source_dir: Path | None,
    *,
    excluded_paths: set[Path],
    excluded_dirs: set[Path],
    excluded_relative_dirs: set[Path],
) -> list[dict[str, object]]:
    files = iter_result_files(
        source_dir,
        excluded_paths=excluded_paths,
        excluded_dirs=excluded_dirs,
        excluded_relative_dirs=excluded_relative_dirs,
    )
    records: list[dict[str, object]] = []
    if source_dir is None:
        return records
    for path in files:
        records.append(
            {
                "source": source_name,
                "relative_path": path.relative_to(source_dir).as_posix(),
                "suffix": path.suffix.lower() or "(no extension)",
                "size_bytes": path.stat().st_size,
                "path": path,
            }
        )
    return records


def main() -> None:
    args = parse_args()

    repo_root = _repo_root()
    results_dir = Path(args.results_dir)
    live_results_dir = Path(args.live_results_dir) if args.live_results_dir else None
    output_dir = Path(args.output_dir)
    figure_dir = Path(args.figure_dir)
    table_dir = Path(args.table_dir)
    manifest_json = Path(args.manifest_json)
    summary_markdown = Path(args.summary_markdown)
    summary_tex = Path(args.summary_tex)
    resolved_live_results_dir = (
        live_results_dir.resolve() if live_results_dir is not None else None
    )
    resolved_output_dir = output_dir.resolve()
    excluded_paths = {
        manifest_json.resolve(),
        summary_markdown.resolve(),
        summary_tex.resolve(),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    figure_dir.mkdir(parents=True, exist_ok=True)
    table_dir.mkdir(parents=True, exist_ok=True)

    source_records = collect_source_files(
        "results",
        results_dir,
        excluded_paths=excluded_paths,
        excluded_dirs={
            resolved_output_dir,
            *(
                {resolved_live_results_dir}
                if resolved_live_results_dir is not None
                else set()
            ),
        },
        excluded_relative_dirs={
            Path("example_live"),
            Path("paper_assets_latest"),
        },
    ) + collect_source_files(
        "live_results",
        live_results_dir,
        excluded_paths=excluded_paths,
        excluded_dirs={resolved_output_dir},
        excluded_relative_dirs=set(),
    )
    counts: Counter[str] = Counter(record["suffix"] for record in source_records)
    source_counts: dict[str, int] = dict(
        sorted(Counter(record["source"] for record in source_records).items())
    )
    files = [
        {
            "source": record["source"],
            "relative_path": record["relative_path"],
            "suffix": record["suffix"],
            "size_bytes": record["size_bytes"],
        }
        for record in source_records
    ]

    staged_figures: list[str] = []
    if figure_dir.exists():
        shutil.rmtree(figure_dir)
    figure_dir.mkdir(parents=True, exist_ok=True)
    staged_figures.extend(
        stage_figures(
            [
                Path(record["path"])
                for record in source_records
                if record["source"] == "results"
            ],
            source_dir=results_dir,
            source_label="results",
            generated_figures_dir=figure_dir,
        )
    )
    if live_results_dir is not None:
        staged_figures.extend(
            stage_figures(
                [
                    Path(record["path"])
                    for record in source_records
                    if record["source"] == "live_results"
                ],
                source_dir=live_results_dir,
                source_label="live_results",
                generated_figures_dir=figure_dir,
            )
        )

    derived_assets = (
        generate_synthetic_fault_assets(
            repo_root=repo_root,
            output_dir=output_dir,
            table_dir=table_dir,
        )
        + generate_trace_probe_assets(
            repo_root=repo_root,
            output_dir=output_dir,
            figure_dir=figure_dir,
            table_dir=table_dir,
        )
        + generate_trace_diagnosis_assets(
            repo_root=repo_root,
            output_dir=output_dir,
            table_dir=table_dir,
        )
        + generate_slow_stream_diagnosis_assets(
            repo_root=repo_root,
            output_dir=output_dir,
            table_dir=table_dir,
        )
        + generate_trace_overhead_assets(
            repo_root=repo_root,
            output_dir=output_dir,
            table_dir=table_dir,
        )
    )

    manifest = {
        "results_dir": results_dir.as_posix(),
        "live_results_dir": live_results_dir.as_posix()
        if live_results_dir is not None
        else None,
        "output_dir": output_dir.as_posix(),
        "total_files": len(files),
        "counts_by_source": source_counts,
        "counts_by_extension": dict(sorted(counts.items())),
        "staged_figures": staged_figures,
        "derived_assets": derived_assets,
        "files": files,
    }
    write_json(manifest_json, manifest)
    write_markdown(
        summary_markdown,
        total_files=len(files),
        total_staged_figures=len(staged_figures),
        counts=counts,
        source_counts=source_counts,
        files=files,
        staged_figures=staged_figures,
        derived_assets=derived_assets,
    )
    write_tex(
        summary_tex,
        total_files=len(files),
        counts=counts,
        source_counts=source_counts,
        staged_figures=staged_figures,
        derived_assets=derived_assets,
    )


if __name__ == "__main__":
    main()
