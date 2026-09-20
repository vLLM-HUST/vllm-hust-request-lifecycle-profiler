from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from vllm_request_lifecycle_profiler.preblind_calibration import (
    CalibrationValidationError,
    build_calibration_report,
    summarize_runtime_run,
)


def _pairs() -> list[dict]:
    totals = (
        (
            {"queue_or_admission": 100, "decode_execution": 50},
            {"queue_or_admission": 102, "decode_execution": 49},
        ),
        (
            {"queue_or_admission": 105, "decode_execution": 50},
            {"queue_or_admission": 101, "decode_execution": 52},
        ),
        (
            {"queue_or_admission": 99, "decode_execution": 50},
            {"queue_or_admission": 105, "decode_execution": 48},
        ),
        (
            {"queue_or_admission": 103, "decode_execution": 50},
            {"queue_or_admission": 102, "decode_execution": 50},
        ),
        (
            {"queue_or_admission": 100, "decode_execution": 50},
            {"queue_or_admission": 112, "decode_execution": 49},
        ),
    )
    pairs = []
    for index, (arm_a, arm_b) in enumerate(totals):
        pairs.append(
            {
                "pair_id": f"null-{index + 1:02d}",
                "order": "AB" if index % 2 == 0 else "BA",
                "workload_id": "oasst1-fixed-64",
                "configuration_id": "qwen14b-tp1-ascend910b2",
                "arm_a": {
                    "run_id": f"a-{index}",
                    "intervention": "none",
                    "evidence_valid": True,
                    "request_count": 64,
                    "candidate_totals_ms": arm_a,
                    "error_count": 0,
                },
                "arm_b": {
                    "run_id": f"b-{index}",
                    "intervention": "none",
                    "evidence_valid": True,
                    "request_count": 64,
                    "candidate_totals_ms": arm_b,
                    "error_count": 0,
                },
            }
        )
    return pairs


def test_build_calibration_report_uses_five_null_pairs() -> None:
    report = build_calibration_report(_pairs())
    assert report["opaque_case_accessed"] is False
    assert report["total_positive_matched_deltas_ms"] == [2.0, 2.0, 6.0, 0, 12.0]
    assert report["null_delta_p95_ms"] == 12.0
    assert report["insufficient_evidence_floor_ms"] == 12.0
    assert report["scorer_configuration"]["bootstrap_seed"] == 2026082701


def test_calibration_floor_excludes_abstention_bucket() -> None:
    pairs = _pairs()
    for index, pair in enumerate(pairs):
        pair["arm_a"]["candidate_totals_ms"]["insufficient_evidence_or_multi_cause"] = (
            10.0
        )
        pair["arm_b"]["candidate_totals_ms"]["insufficient_evidence_or_multi_cause"] = (
            10_000.0 + index
        )

    report = build_calibration_report(pairs)

    assert report["total_positive_matched_deltas_ms"] == [
        2.0,
        2.0,
        6.0,
        0,
        12.0,
    ]
    assert report["null_delta_p95_ms"] == 12.0


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda pairs: pairs.pop(), "exactly five"),
        (lambda pairs: pairs[1].update(order="AB"), "alternate"),
        (
            lambda pairs: pairs[0]["arm_b"].update(intervention="queue_delay"),
            "no-intervention",
        ),
        (
            lambda pairs: pairs[0]["arm_b"].update(evidence_valid=False),
            "evidence must be valid",
        ),
        (lambda pairs: pairs[0]["arm_b"].update(error_count=1), "must be zero"),
        (
            lambda pairs: pairs[0]["arm_b"].update(request_count=63),
            "unmatched request counts",
        ),
        (
            lambda pairs: pairs[0]["arm_b"]["candidate_totals_ms"].pop(
                "decode_execution"
            ),
            "unmatched candidates",
        ),
        (
            lambda pairs: pairs[1].update(workload_id="different-workload"),
            "same workload and configuration",
        ),
        (
            lambda pairs: (
                pairs[1]["arm_a"].update(request_count=32),
                pairs[1]["arm_b"].update(request_count=32),
            ),
            "same request count",
        ),
        (
            lambda pairs: (
                pairs[1]["arm_a"]["candidate_totals_ms"].update(extra=1.0),
                pairs[1]["arm_b"]["candidate_totals_ms"].update(extra=1.0),
            ),
            "same candidate set",
        ),
    ],
)
def test_calibration_rejects_invalid_or_non_null_input(mutation, message) -> None:
    pairs = copy.deepcopy(_pairs())
    mutation(pairs)
    with pytest.raises(CalibrationValidationError, match=message):
        build_calibration_report(pairs)


def test_calibration_rejects_unknown_answer_bearing_data() -> None:
    pairs = _pairs()
    pairs[0]["oracle"] = "hidden"
    with pytest.raises(CalibrationValidationError, match="unknown=.*oracle"):
        build_calibration_report(pairs)


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value) + "\n")


def test_summarize_runtime_run_uses_only_closed_supported_spans(tmp_path: Path) -> None:
    _write_json(tmp_path / "analysis.json", {"evidence_valid": True})
    _write_json(
        tmp_path / "client_results.json",
        {"results": [{"http_status": 200, "error": None}]},
    )
    _write_json(tmp_path / "manifest.json", {"run_id": "run-01"})
    records = [
        {"record_type": "process_start", "process_uuid": "p1"},
        {
            "record_type": "event",
            "process_uuid": "p1",
            "event_name": "queued",
            "timestamp_ns": 10,
            "start_span_id": "s1",
            "end_span_id": None,
        },
        {
            "record_type": "event",
            "process_uuid": "p1",
            "event_name": "scheduled",
            "timestamp_ns": 2_000_010,
            "start_span_id": None,
            "end_span_id": "s1",
        },
        {
            "record_type": "event",
            "process_uuid": "p1",
            "event_name": "prefill_started",
            "timestamp_ns": 3_000_000,
            "start_span_id": "s2",
            "end_span_id": None,
        },
        {
            "record_type": "event",
            "process_uuid": "p1",
            "event_name": "prefill_done",
            "timestamp_ns": 8_000_000,
            "start_span_id": None,
            "end_span_id": "s2",
        },
        {
            "record_type": "process_summary",
            "process_uuid": "p1",
            "close_outcome": "drained",
            "dropped_data_count": 0,
            "dropped_control_count": 0,
            "writer_failure_count": 0,
        },
    ]
    (tmp_path / "trace.rlp.p1.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records)
    )

    summary = summarize_runtime_run(tmp_path)

    assert summary == {
        "run_id": "run-01",
        "intervention": "none",
        "evidence_valid": True,
        "request_count": 1,
        "candidate_totals_ms": {
            "insufficient_evidence_or_multi_cause": 5.0,
            "queue_or_admission": 2.0,
        },
        "error_count": 0,
    }


def test_summarize_runtime_run_fails_evidence_on_missing_summary(
    tmp_path: Path,
) -> None:
    _write_json(tmp_path / "analysis.json", {"evidence_valid": True})
    _write_json(
        tmp_path / "client_results.json",
        {"results": [{"http_status": 200, "error": None}]},
    )
    _write_json(tmp_path / "manifest.json", {"run_id": "run-01"})
    (tmp_path / "trace.rlp.p1.jsonl").write_text(
        json.dumps({"record_type": "process_start", "process_uuid": "p1"}) + "\n"
    )
    assert summarize_runtime_run(tmp_path)["evidence_valid"] is False


def test_summarize_runtime_run_fails_evidence_on_control_loss(tmp_path: Path) -> None:
    _write_json(tmp_path / "analysis.json", {"evidence_valid": True})
    _write_json(
        tmp_path / "client_results.json",
        {"results": [{"http_status": 200, "error": None}]},
    )
    _write_json(tmp_path / "manifest.json", {"run_id": "run-01"})
    records = [
        {"record_type": "process_start", "process_uuid": "p1"},
        {
            "record_type": "process_summary",
            "process_uuid": "p1",
            "close_outcome": "drained",
            "dropped_data_count": 0,
            "dropped_control_count": 1,
            "writer_failure_count": 0,
        },
    ]
    (tmp_path / "trace.rlp.p1.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records)
    )

    assert summarize_runtime_run(tmp_path)["evidence_valid"] is False
