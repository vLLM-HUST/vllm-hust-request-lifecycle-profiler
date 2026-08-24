from __future__ import annotations

from pathlib import Path

from vllm_request_lifecycle_profiler.issue19_public_artifacts import (
    Redactor,
    verify_public_artifacts,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_ROOT = REPO_ROOT / (
    ".benchmarks/results/m0_issue19_public/20260822-sanitized-corrected-paired-10"
)


def test_redactor_preserves_identity_relationship_without_machine_values() -> None:
    redactor = Redactor(
        pids={"12345": "PID_001"},
        ports={"18179": "SERVICE_PORT"},
        devices={"7": "NPU_TARGET"},
    )
    source = {
        "pid": 12345,
        "worker_generation": "VllmWorker-0:12345",
        "port": 18179,
        "device": 7,
        "path": (
            "/root/vllm-request-lifecycle-profiler-plugin-issue19-m0/"
            "worker_failure/12345.pending-transfer.json"
        ),
        "endpoint": "http://127.0.0.1:18179/v1/chat/completions",
    }

    public = redactor.value(source)

    assert public["pid"] == "PID_001"
    assert public["worker_generation"] == "VllmWorker-0:PID_001"
    assert public["port"] == "SERVICE_PORT"
    assert public["device"] == "NPU_TARGET"
    assert public["path"] == "$WORKTREE/worker_failure/PID_001.pending-transfer.json"
    assert public["endpoint"] == "http://$PRIVATE_HOST:SERVICE_PORT/v1/chat/completions"


def test_checked_in_public_export_is_reproducible_and_no_go() -> None:
    result = verify_public_artifacts(PUBLIC_ROOT)

    assert result == {
        "correctness_100_percent": False,
        "decision": "NO_GO",
        "evidence_valid_100_percent": True,
        "latency_pathology_repetition_count": 0,
        "resource_pathology_repetition_count": 1,
        "verified_public_file_count": 272,
    }
