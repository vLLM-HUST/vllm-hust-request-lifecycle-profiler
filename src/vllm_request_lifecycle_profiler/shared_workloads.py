from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from pathlib import Path
from statistics import mean
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]


class WhitespaceTokenizer:
	def encode(self, text: str, add_special_tokens: bool = False) -> list[str]:
		del add_special_tokens
		return text.split()


def _candidate_workload_src_paths() -> tuple[Path, ...]:
	configured = os.environ.get("LLM_SERVING_WORKLOADS_SRC", "").strip()
	paths: list[Path] = []
	if configured:
		paths.append(Path(configured).expanduser())
	paths.append(REPO_ROOT.parent / "llm-serving-workloads" / "src")
	return tuple(paths)


def load_workloads_module() -> Any:
	for candidate in _candidate_workload_src_paths():
		if not candidate.is_dir():
			continue
		candidate_str = str(candidate)
		if candidate_str not in sys.path:
			sys.path.insert(0, candidate_str)
		break
	try:
		return importlib.import_module("llm_serving_workloads")
	except ImportError as exc:
		raise RuntimeError(
			"llm-serving-workloads is required for shared-workload tests. "
			"Set LLM_SERVING_WORKLOADS_SRC=<repo>/src or install the package first."
		) from exc


def resolve_case_spec(case_id: str) -> dict[str, Any]:
	workloads = load_workloads_module()
	catalog = workloads.SHARED_BENCHMARK_CASE_CATALOG
	if case_id not in catalog:
		raise ValueError(f"unknown workload case: {case_id}")
	return dict(catalog[case_id])


def generate_case_requests(case_id: str, *, seed: int) -> list[Any]:
	workloads = load_workloads_module()
	case = resolve_case_spec(case_id)
	dataset_name = str(case["dataset_name"])
	if not workloads.is_repo_local_workload_dataset(dataset_name):
		raise ValueError(
			f"workload case {case_id} uses dataset {dataset_name}, which is outside the repo-local smoke surface"
		)
	return workloads.generate_repo_local_workload_requests(
		dataset_name=dataset_name,
		tokenizer=WhitespaceTokenizer(),
		dp_size=int(case.get("dp_size", 8)),
		num_prompts=int(case.get("num_prompts", int(case["num_groups"]) * int(case["prompts_per_group"]))),
		num_groups=int(case["num_groups"]),
		system_prompt_len=int(case["system_prompt_len"]),
		question_len=int(case["question_len"]),
		output_len=int(case["output_len"]),
		seed=seed,
		**dict(case.get("benchmark_kwargs", {})),
	)


def supported_shared_case_ids() -> tuple[str, ...]:
	workloads = load_workloads_module()
	case_ids: list[str] = []
	for case_id in workloads.DEFAULT_SHARED_BENCHMARK_CASE_ORDER:
		spec = dict(workloads.SHARED_BENCHMARK_CASE_CATALOG[case_id])
		if workloads.is_repo_local_workload_dataset(str(spec["dataset_name"])):
			case_ids.append(case_id)
	return tuple(case_ids)


def summarize_case(case_id: str, *, seed: int) -> dict[str, Any]:
	workloads = load_workloads_module()
	case = resolve_case_spec(case_id)
	rows = generate_case_requests(case_id, seed=seed)
	summary = workloads.summarize_repo_local_workload(rows)
	if summary is None:
		raise ValueError(f"workload case {case_id} did not emit repo-local metadata")
	return {
		"case_id": case_id,
		"label": str(case.get("label", case_id)),
		"dataset_name": str(case["dataset_name"]),
		"dp_size": int(case.get("dp_size", 8)),
		"mean_prompt_len": round(mean(row.prompt_len for row in rows), 3),
		"mean_output_len": round(mean(row.output_len for row in rows), 3),
		"summary": summary,
	}


def build_shared_workload_report(*, seed: int, include_unsupported: bool = True) -> dict[str, Any]:
	workloads = load_workloads_module()
	supported_cases: list[dict[str, Any]] = []
	skipped_cases: list[dict[str, Any]] = []
	for case_id in workloads.DEFAULT_SHARED_BENCHMARK_CASE_ORDER:
		spec = dict(workloads.SHARED_BENCHMARK_CASE_CATALOG[case_id])
		if workloads.is_repo_local_workload_dataset(str(spec["dataset_name"])):
			supported_cases.append(summarize_case(case_id, seed=seed))
		elif include_unsupported:
			skipped_cases.append(
				{
					"case_id": case_id,
					"label": str(spec.get("label", case_id)),
					"dataset_name": str(spec["dataset_name"]),
					"reason": "non_repo_local_boundary_case",
				}
			)
	return {
		"seed": seed,
		"supported_case_count": len(supported_cases),
		"skipped_case_count": len(skipped_cases),
		"supported_cases": supported_cases,
		"skipped_cases": skipped_cases,
	}


def render_markdown(report: dict[str, Any]) -> str:
	lines = ["# Shared Workload Smoke Report", ""]
	lines.append(f"- seed: {report['seed']}")
	lines.append(f"- supported cases: {report['supported_case_count']}")
	lines.append(f"- skipped cases: {report['skipped_case_count']}")
	lines.append("")
	for case in report["supported_cases"]:
		summary = case["summary"]
		lines.append(f"## {case['case_id']}")
		lines.append("")
		lines.append(f"- label: {case['label']}")
		lines.append(f"- dataset: {case['dataset_name']}")
		lines.append(f"- requests: {summary['request_count']}")
		lines.append(f"- family: {summary['workload_family']}")
		lines.append(f"- anchors: {summary['primary_anchor_count']} primary / {summary['secondary_anchor_count']} secondary")
		lines.append(f"- anchor rank coverage: {summary['anchor_rank_coverage']}")
		lines.append(f"- mean prompt len: {case['mean_prompt_len']}")
		lines.append(f"- mean output len: {case['mean_output_len']}")
		lines.append("")
	if report["skipped_cases"]:
		lines.append("## Skipped Cases")
		lines.append("")
		for case in report["skipped_cases"]:
			lines.append(f"- {case['case_id']}: {case['reason']}")
	return "\n".join(lines) + "\n"


def main() -> None:
	parser = argparse.ArgumentParser(description="Run the template shared-workload smoke harness.")
	parser.add_argument("--seed", type=int, default=7)
	parser.add_argument("--output-json")
	parser.add_argument("--output-markdown")
	parser.add_argument("--skip-unsupported", action="store_true")
	args = parser.parse_args()

	report = build_shared_workload_report(seed=args.seed, include_unsupported=not args.skip_unsupported)
	if args.output_json:
		output_json = Path(args.output_json)
		output_json.parent.mkdir(parents=True, exist_ok=True)
		output_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
	if args.output_markdown:
		output_markdown = Path(args.output_markdown)
		output_markdown.parent.mkdir(parents=True, exist_ok=True)
		output_markdown.write_text(render_markdown(report), encoding="utf-8")
	if not args.output_json and not args.output_markdown:
		print(json.dumps(report, indent=2, sort_keys=True))


__all__ = [
	"WhitespaceTokenizer",
	"build_shared_workload_report",
	"generate_case_requests",
	"load_workloads_module",
	"main",
	"render_markdown",
	"resolve_case_spec",
	"summarize_case",
	"supported_shared_case_ids",
]