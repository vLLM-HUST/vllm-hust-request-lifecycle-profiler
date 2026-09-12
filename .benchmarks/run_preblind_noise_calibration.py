"""Run the public five-pair no-intervention calibration on one NPU.

Both arms execute the same fixed OASST1 workload and service configuration.
The raw service directories remain local; the reducer emits an oracle-free
summary suitable for review and later publication.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from vllm_request_lifecycle_profiler.oasst1_workload import (
    DEFAULT_DATA_CACHE,
    OASST1_FILENAME,
    build_oasst1_repetitions,
)
from vllm_request_lifecycle_profiler.preblind_calibration import (
    build_calibration_report,
    summarize_runtime_run,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ISSUE19_RUNNER = REPO_ROOT / ".benchmarks" / "run_issue19_m0_baseline.py"
PAIR_ORDERS = ("AB", "BA", "AB", "BA", "AB")
WORKLOAD_ID = "oasst1-fixed-64-v1"
CONFIGURATION_ID = "qwen2.5-14b-tp1-ascend910b2-kv2g-eager-v1"
EXPECTED_COMMITS = {
    "third_party/vllm-hust": "c180d643c66f7a12434ae551cfc83cd7b7795302",
    "third_party/vllm-ascend-hust": "95f390bb7816b5d557eb327c110b801f2a5b2cf5",
    "third_party/llm-serving-workloads": ("76e24c85bcab76ecfabb831c9444002b6efffd58"),
    "third_party/oasst1": "fdf72ae0827c1cda404aff25b6603abec9e3399b",
    "third_party/traceloom": "63e86fc5095ee2552400c8a6c2c863faeaabf0b4",
}


def _load_issue19_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "request_lifecycle_issue19_runner", ISSUE19_RUNNER
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the existing real-service runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(spec.name, None)
        raise
    return module


def _git_head(path: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _git_clean(path: Path) -> bool:
    return not subprocess.run(
        ["git", "-C", str(path), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _validate_source_checkouts() -> dict[str, str]:
    observed: dict[str, str] = {}
    for relative_path, expected in EXPECTED_COMMITS.items():
        checkout = REPO_ROOT / relative_path
        head = _git_head(checkout)
        if head != expected:
            raise RuntimeError(f"{relative_path} must be at {expected}, found {head}")
        if not _git_clean(checkout):
            raise RuntimeError(f"{relative_path} must be clean")
        observed[relative_path] = head
    return observed


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _run_dir(root: Path, repetition: int, seed: int) -> Path:
    return root / f"r{repetition:02d}-{seed}-normal-control"


def _run_arm(
    runner: ModuleType,
    repetition: int,
    workload: tuple[Any, ...],
    *,
    device: int,
    port: int,
    output_root: Path,
) -> dict[str, Any]:
    analysis = runner._run_normal_control(
        repetition,
        workload,
        device=device,
        port=port,
        output_root=output_root,
    )
    if analysis.get("evidence_valid") is not True:
        raise RuntimeError("calibration arm produced invalid evidence")
    run_dir = _run_dir(output_root, repetition, runner.SEEDS[repetition])
    summary = summarize_runtime_run(run_dir)
    if summary["evidence_valid"] is not True:
        raise RuntimeError("calibration reducer rejected the real-service arm")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", type=int, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if not 0 <= args.device <= 7:
        parser.error("device must be in [0, 7]")
    if not 1 <= args.port <= 65535:
        parser.error("port must be in [1, 65535]")
    if not _git_clean(REPO_ROOT):
        raise RuntimeError("calibration requires a clean profiler checkout")
    source_commits = _validate_source_checkouts()

    runner = _load_issue19_runner()
    repetitions = build_oasst1_repetitions(DEFAULT_DATA_CACHE / OASST1_FILENAME)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    plan = {
        "schema": "request-lifecycle-preblind-null-plan/v1",
        "evidence_class": "real-online",
        "opaque_case_accessed": False,
        "intervention": "none",
        "pair_orders": list(PAIR_ORDERS),
        "profiler_commit": _git_head(REPO_ROOT),
        "runtime_commit": source_commits["third_party/vllm-hust"],
        "ascend_commit": source_commits["third_party/vllm-ascend-hust"],
        "workload_commit": source_commits["third_party/llm-serving-workloads"],
        "oasst1_commit": source_commits["third_party/oasst1"],
        "traceloom_commit": source_commits["third_party/traceloom"],
        "workload_id": WORKLOAD_ID,
        "configuration_id": CONFIGURATION_ID,
    }
    _write_json(output / "plan.json", plan)

    pairs: list[dict[str, Any]] = []
    for index, order in enumerate(PAIR_ORDERS):
        pair_root = output / f"pair-{index + 1:02d}"
        launch_order = ("arm_a", "arm_b") if order == "AB" else ("arm_b", "arm_a")
        summaries: dict[str, dict[str, Any]] = {}
        for arm in launch_order:
            summaries[arm] = _run_arm(
                runner,
                index,
                repetitions[index],
                device=args.device,
                port=args.port,
                output_root=pair_root / arm,
            )
        pair = {
            "pair_id": f"null-{index + 1:02d}",
            "order": order,
            "workload_id": WORKLOAD_ID,
            "configuration_id": CONFIGURATION_ID,
            **summaries,
        }
        pairs.append(pair)
        _write_json(output / "calibration_pairs.json", pairs)
        print(
            json.dumps(
                {
                    "pair": index + 1,
                    "order": order,
                    "status": "valid",
                },
                sort_keys=True,
            ),
            flush=True,
        )

    report = {**plan, **build_calibration_report(pairs), "pairs": pairs}
    _write_json(output / "calibration_report.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
