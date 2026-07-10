from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from vllm_request_lifecycle_profiler.trace import evaluate_fault_injection_matrix
from vllm_request_lifecycle_profiler.trace import synthetic_fault_scenarios


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKLOAD_SUBMODULE = REPO_ROOT / "third_party" / "llm-serving-workloads"


def _git(args: list[str], *, cwd: Path = REPO_ROOT) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def _git_status(cwd: Path) -> str:
    return _git(["status", "--short"], cwd=cwd)


def _metadata(output_dir: Path) -> dict[str, Any]:
    workload_commit = None
    workload_branch = None
    workload_dirty = None
    if WORKLOAD_SUBMODULE.is_dir():
        workload_commit = _git(["rev-parse", "HEAD"], cwd=WORKLOAD_SUBMODULE)
        workload_branch = _git(["branch", "--show-current"], cwd=WORKLOAD_SUBMODULE)
        workload_dirty = bool(_git_status(WORKLOAD_SUBMODULE))

    return {
        "evidence_label": "simulation/model",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "command": " ".join(sys.argv),
        "output_dir": str(output_dir),
        "parent_commit": _git(["rev-parse", "HEAD"]),
        "parent_branch": _git(["branch", "--show-current"]),
        "parent_dirty": bool(_git_status(REPO_ROOT)),
        "npu_id": None,
        "hardware": "not_used",
        "model": "synthetic_fault_injection",
        "runtime": "no_serving_runtime",
        "conda_env": os.environ.get("CONDA_DEFAULT_ENV", ""),
        "workload_source": {
            "path": str(WORKLOAD_SUBMODULE),
            "commit": workload_commit,
            "branch": workload_branch,
            "dirty": workload_dirty,
        },
        "fault_model": "deterministic_synthetic_lifecycle_spans",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run deterministic no-NPU lifecycle fault-injection attribution."
    )
    parser.add_argument(
        "--output-dir",
        default=".benchmarks/results/synthetic_fault_injection",
        help="Directory for matrix.json and run_metadata.json.",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    matrix = evaluate_fault_injection_matrix(synthetic_fault_scenarios())
    (output_dir / "matrix.json").write_text(
        json.dumps(asdict(matrix), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output_dir / "run_metadata.json").write_text(
        json.dumps(_metadata(output_dir), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                "scenario_count": matrix.scenario_count,
                "accuracy": matrix.accuracy,
                "false_positive_count": matrix.false_positive_count,
                "false_negative_count": matrix.false_negative_count,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
