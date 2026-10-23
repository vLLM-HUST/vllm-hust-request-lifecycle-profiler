from __future__ import annotations

import os
from pathlib import Path

from vllm_request_lifecycle_profiler.issue19_public_artifacts import (
    Redactor,
    verify_public_artifacts,
)



def test_redactor_preserves_identity_relationship_without_machine_values() -> None:
    redactor = Redactor(
        pids={"54321": "PID_001"},
        ports={"29431": "SERVICE_PORT"},
        devices={"3": "NPU_TARGET"},
        clock_domains={
            "1234567890abcdef1234567890abcdef": "00000000000000000000000000000001"
        },
        model_paths=("/opt/models/example-model",),
    )
    source = {
        "pid": 54321,
        "worker_generation": "VllmWorker-0:54321",
        "port": 29431,
        "device": 3,
        "clock_domain_id": "1234567890abcdef1234567890abcdef",
        "model_path": "/opt/models/example-model",
        "path": (
            "/opt/experiment/worker_failure/54321.pending-transfer.json"
        ),
        "endpoint": "http://127.0.0.1:29431/v1/chat/completions",
    }

    public = redactor.value(source)

    assert public["pid"] == "PID_001"
    assert public["worker_generation"] == "VllmWorker-0:PID_001"
    assert public["port"] == "SERVICE_PORT"
    assert public["device"] == "NPU_TARGET"
    assert public["clock_domain_id"] == "00000000000000000000000000000001"
    assert public["model_path"] == "$MODEL_DIR"
    assert public["path"] == "$HOST_PATH"
    assert public["endpoint"] == "http://$PRIVATE_HOST:SERVICE_PORT/v1/chat/completions"


def test_canonical_public_export_is_reproducible_and_no_go() -> None:
    public_root = Path(os.environ["BENCHMARK_EVIDENCE_ROOT"]) / (
        ".benchmarks/results/m0_issue19_public/20260822-sanitized-corrected-paired-10"
    )
    result = verify_public_artifacts(public_root)

    assert result == {
        "correctness_100_percent": False,
        "decision": "NO_GO",
        "evidence_valid_100_percent": True,
        "latency_pathology_repetition_count": 0,
        "resource_pathology_repetition_count": 1,
        "verified_public_file_count": 272,
    }
