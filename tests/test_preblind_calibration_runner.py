from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


def _load_runner():
    path = (
        Path(__file__).resolve().parents[1]
        / ".benchmarks"
        / "run_preblind_noise_calibration.py"
    )
    spec = importlib.util.spec_from_file_location("preblind_runner", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_calibration_runner_fixes_five_alternating_pairs() -> None:
    runner = _load_runner()
    assert runner.PAIR_ORDERS == ("AB", "BA", "AB", "BA", "AB")
    assert runner.WORKLOAD_ID == "oasst1-fixed-64-v1"
    assert "issue19" in runner.ISSUE19_RUNNER.name


def test_calibration_runner_loads_existing_real_service_runner() -> None:
    runner = _load_runner()

    existing = runner._load_issue19_runner()

    assert callable(existing._run_normal_control)
    assert len(existing.SEEDS) >= len(runner.PAIR_ORDERS)


def test_calibration_runner_rejects_wrong_source_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    monkeypatch.setattr(runner, "_git_clean", lambda path: True)
    monkeypatch.setattr(runner, "_git_head", lambda path: "wrong")

    with pytest.raises(RuntimeError, match="must be at"):
        runner._validate_source_checkouts()


def test_public_target_covers_all_requests_in_execution_order() -> None:
    root = Path(__file__).resolve().parents[1]
    target = json.loads(
        (root / "docs" / "blind_attribution_preblind_target.json").read_text()
    )
    workload = target["workload"]
    execution_order = [
        *workload["initial_arrival_order"],
        workload["final_request_ordinal"],
    ]

    assert len(execution_order) == workload["requests_per_lifecycle"] == 64
    assert sorted(execution_order) == list(range(64))
