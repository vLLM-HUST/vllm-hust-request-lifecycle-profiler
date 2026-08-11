"""Tests for the M0 evaluation pipeline (development-level)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vllm_request_lifecycle_profiler.m0_evaluation import (
    RequestPhases,
    aggregate_phases,
    diff_phases,
    evaluate_case,
    rank_mechanisms,
)


def _case_restore():
    base = [
        RequestPhases("a", {"decode": 385_000.0}),
        RequestPhases("b", {"decode": 384_000.0}),
        RequestPhases("c", {"decode": 383_000.0}),
    ]
    anom = [
        RequestPhases("a", {"kv_recovery": 41_000.0, "decode": 378_000.0}),
        RequestPhases("b", {"decode": 377_000.0}),
        RequestPhases("c", {"decode": 376_000.0}),
    ]
    return base, anom


def _case_prefill():
    base = [RequestPhases("p1", {"prefill": 65.0, "decode": 102.0})]
    anom = [RequestPhases("p1", {"prefill": 98.0, "decode": 102.0})]
    return base, anom


def test_aggregate_and_diff():
    base, anom = _case_restore()
    b = aggregate_phases(base)
    a = aggregate_phases(anom)
    d = diff_phases(b, a)
    assert d["kv_recovery"] > 40_000.0
    assert d["decode"] < 0  # decode median drops (restore tail moves time into kv_recovery)


def test_rank_restore_first():
    base, anom = _case_restore()
    rep = evaluate_case(base, anom, case_id="t-restore", ground_truth="restore/wakeup")
    assert rep.ranking and rep.ranking[0].mechanism == "restore/wakeup"
    assert rep.top1_ok is True
    assert rep.mrr == 1.0
    assert not rep.abstained


def test_rank_prefill_first():
    base, anom = _case_prefill()
    rep = evaluate_case(base, anom, case_id="t-prefill", ground_truth="prefill")
    assert rep.ranking and rep.ranking[0].mechanism == "prefill"
    assert rep.top1_ok is True


def test_abstain_no_single_root_cause():
    base = [
        RequestPhases("s1", {"queueing": 100.0, "prefill": 200.0, "decode": 300.0}),
        RequestPhases("s2", {"queueing": 110.0, "prefill": 210.0, "decode": 310.0}),
    ]
    anom = [
        RequestPhases("s1", {"queueing": 125.0, "prefill": 220.0, "decode": 320.0}),
        RequestPhases("s2", {"queueing": 130.0, "prefill": 230.0, "decode": 330.0}),
    ]
    rep = evaluate_case(base, anom, case_id="t-abstain", ground_truth=None, abstain_threshold_ms=1.0)
    assert rep.abstained
    assert rep.abstain_reason == "no_single_root_cause"


def test_abstain_insufficient_evidence():
    base = [RequestPhases("x", {"decode": 100.0})]
    anom = [RequestPhases("x", {"decode": 101.0})]
    rep = evaluate_case(base, anom, case_id="t-low", ground_truth=None, abstain_threshold_ms=50.0)
    assert rep.abstained
    assert rep.abstain_reason == "insufficient_evidence"
