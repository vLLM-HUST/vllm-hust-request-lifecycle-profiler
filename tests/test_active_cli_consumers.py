"""Exercise maintained offline CLI readers against immutable external evidence."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("consumer", ["matrix", "pair", "anomaly", "diagnosis"])
def test_active_collection_cli_reads_external_inputs_without_mutation(
    tmp_path, consumer
):
    external = os.environ.get("BENCHMARK_COLLECTION_ROOT")
    if not external:
        pytest.skip("Canonical consumer CI supplies the verified archive root")
    source = Path(external)
    results = source / ".benchmarks/results"
    output = tmp_path / consumer
    commands = {
        "matrix": ["analyze_controlled_fault_matrix.py"],
        "pair": [
            "run_runtime_hook_pair_plan.py",
            "--hook-disabled-dir",
            str(results / "npu6_runtime_hooks_disabled_low_overhead_baseline"),
            "--hook-enabled-dir",
            str(results / "npu6_runtime_hooks_low_overhead_enabled_smoke"),
            "--trace-export-path",
            str(
                results
                / "npu6_runtime_hooks_low_overhead_enabled_smoke/runtime_trace.jsonl"
            ),
        ],
        "anomaly": [
            "analyze_runtime_concurrency_anomaly.py",
            "--input-dir",
            str(results / "npu6_runtime_hooks_concurrency_sweep"),
            "--runtime-trace",
            str(results / "npu6_runtime_hooks_concurrency_sweep/runtime_trace.jsonl"),
        ],
        "diagnosis": [
            "analyze_trace_diagnosis.py",
            "--input-probe-results",
            str(
                results
                / "npu6_existing_server_trace_probe_repeated_smoke/probe_results.json"
            ),
        ],
    }
    before = {
        p: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in source.rglob("*")
        if p.is_file()
    }
    command = commands[consumer]
    subprocess.run(
        [
            sys.executable,
            str(ROOT / ".benchmarks" / command[0]),
            *command[1:],
            "--output-dir",
            str(output),
        ],
        cwd=ROOT,
        env=dict(os.environ, PYTHONPATH=str(ROOT / "src")),
        capture_output=True,
        text=True,
        check=True,
    )
    summary = json.loads((output / "summary.json").read_text())
    assert summary
    if consumer == "matrix":
        assert summary["real_online_matrix_status"] == "incomplete"
        assert summary["missing_classes"]
    elif consumer == "pair":
        assert summary["loaded_result_count"] == 2
        assert summary["missing_result_count"] == 0
    elif consumer == "anomaly":
        assert summary["diagnosis"]["root_cause_status"] == "unresolved"
    after = {
        p: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in source.rglob("*")
        if p.is_file()
    }
    assert after == before
