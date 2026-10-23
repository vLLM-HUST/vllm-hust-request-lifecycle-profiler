"""Historical paper inputs must not silently disappear after migration."""

import importlib.util
import os
from pathlib import Path

import pytest


def exporter():
    path = (
        Path(__file__).resolve().parents[1]
        / "paper/request_lifecycle_causal_profiler/experiments/export_paper_assets.py"
    )
    spec = importlib.util.spec_from_file_location("historical_paper_export", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_absent_overhead_fails_closed(tmp_path):
    with pytest.raises(FileNotFoundError):
        exporter()._trace_overhead_rows(tmp_path)


def test_canonical_overhead_modes():
    root = Path(os.environ["BENCHMARK_HISTORY_ROOT"])
    rows = exporter()._trace_overhead_rows(root)
    assert {row["mode"] for row in rows} == {"no-trace", "trace"}
    assert all(row["request_count"] == row["success_count"] == 12 for row in rows)
    traced = next(row for row in rows if row["mode"] == "trace")
    assert traced["event_count"] == 117
