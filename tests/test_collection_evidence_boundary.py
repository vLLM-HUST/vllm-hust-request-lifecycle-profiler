"""Only reviewed code/configuration and forwarding documents remain in migrated collections."""

import subprocess
from pathlib import Path

PREFIXES = [".benchmarks/results/"]
RETAINED = [
    ".benchmarks/results/npu6_controlled_fault_matrix/matrix.md",
    ".benchmarks/results/npu6_runtime_hooks_concurrency_sweep/concurrency_anomaly_analysis/anomaly_analysis.md",
    ".benchmarks/results/npu6_runtime_hooks_concurrency_sweep/concurrency_sweep_summary.md",
    ".benchmarks/results/npu6_runtime_hooks_concurrency_sweep/runtime_internal_span_analysis.md",
    ".benchmarks/results/shared_workloads_smoke.md",
]


def test_migrated_collection_boundary():
    root = Path(__file__).resolve().parents[1]
    actual = subprocess.check_output(
        ["git", "-C", str(root), "ls-files", "--", *PREFIXES], text=True
    ).splitlines()
    assert set(actual) == set(RETAINED), (
        "Review new code or migrate original data to benchmark"
    )
