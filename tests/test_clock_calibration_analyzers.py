from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_benchmark_module(filename: str):
    path = REPO_ROOT / ".benchmarks" / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _accepted_capture() -> dict[str, object]:
    return {
        "alignment_status": "calibrated",
        "audit_status": "PASS",
        "input_marker_count": 6,
        "inlier_marker_count": 6,
        "rejected_marker_count": 0,
        "fit_marker_count": 5,
        "validation_marker_count": 1,
        "marker_resolution": {
            "direct_overlap_count": 0,
            "observed_method_counts": {"ordinal_affine_fallback": 6},
        },
    }


def test_calibration_acceptance_requires_minimum_and_holdout() -> None:
    module = _load_benchmark_module("analyze_host_device_clock_calibration.py")
    capture = _accepted_capture()
    assert module._capture_meets_acceptance_contract(capture)

    capture["input_marker_count"] = 5
    assert not module._capture_meets_acceptance_contract(capture)
    capture["input_marker_count"] = 6
    capture["validation_marker_count"] = 0
    capture["fit_marker_count"] = 6
    assert not module._capture_meets_acceptance_contract(capture)

    capture = _accepted_capture()
    capture["input_marker_count"] = 7
    capture["rejected_marker_count"] = 2
    assert not module._capture_meets_acceptance_contract(capture)

    capture = _accepted_capture()
    capture["inlier_marker_count"] = 5
    capture["fit_marker_count"] = 4
    capture["rejected_marker_count"] = 1
    assert not module._capture_meets_acceptance_contract(capture)


def test_calibration_acceptance_rejects_direct_or_unknown_resolution() -> None:
    module = _load_benchmark_module("analyze_host_device_clock_calibration.py")
    capture = _accepted_capture()
    capture["marker_resolution"] = {
        "direct_overlap_count": 1,
        "observed_method_counts": {"direct_overlap": 1},
    }
    assert not module._capture_meets_acceptance_contract(capture)
    with pytest.raises(ValueError, match="unsupported"):
        module._require_real_resolution_method(Path("capture.db"), "heuristic")


def test_overhead_source_gate_rejects_dirty_or_mismatched_revision() -> None:
    module = _load_benchmark_module("analyze_npu6_clock_marker_overhead_ab.py")
    disabled = {
        "repo": {"commit": "a" * 40, "dirty_excluding_output_dir": False},
        "workload_source": {"commit": "b" * 40, "dirty": False},
    }
    enabled = {
        "repo": {"commit": "a" * 40, "dirty_excluding_output_dir": False},
        "workload_source": {"commit": "b" * 40, "dirty": False},
    }
    assert all(module._source_matching_checks(disabled, enabled).values())

    enabled["repo"]["dirty_excluding_output_dir"] = True
    assert not module._source_matching_checks(disabled, enabled)[
        "probe_repository_clean"
    ]
    enabled["repo"]["dirty_excluding_output_dir"] = False
    enabled["repo"]["commit"] = "c" * 40
    assert not module._source_matching_checks(disabled, enabled)[
        "probe_repository_revision"
    ]
