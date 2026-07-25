from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    path = (
        Path(__file__).resolve().parents[1]
        / ".benchmarks"
        / "analyze_controlled_fault_matrix.py"
    )
    spec = importlib.util.spec_from_file_location("analyze_controlled_fault_matrix", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_fault_matrix_keeps_probe_boundary_and_missing_live_gates() -> None:
    module = _load_module()

    result = module.build_matrix()

    summary = result["summary"]
    assert summary["evidence_label"] == "derived-artifact"
    assert summary["real_online_matrix_status"] == "incomplete"
    assert summary["available_case_count"] >= 4
    assert summary["missing_real_online_case_count"] == 3
    assert set(summary["missing_classes"]) == {
        "queue_pressure",
        "kv_pressure",
        "cleanup_stall",
    }
    assert "not a repo-launched real-online" in summary["claim_boundary"]
    assert all(
        row["result_valid_for_internal_only_accuracy_claims"] is False
        for row in result["rows"]
    )


def test_baseline_rows_mark_raw_logs_and_manual_as_missing() -> None:
    module = _load_module()

    rows = module._baseline_rows(
        expected="decode",
        observed="decode",
        missing_event_p95=0.0,
    )

    by_name = {row["baseline"]: row for row in rows}
    assert by_name["causal_rules_enabled"]["correct"] is True
    assert by_name["simple_stage_timer"]["status"] == "available"
    assert by_name["raw_logs"]["status"] == "missing"
    assert by_name["manual_posthoc"]["time_to_root_cause_measurement"] == "not_measured"
