from __future__ import annotations

import copy
import importlib.util
import json
from decimal import Decimal
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


def test_calibration_distribution_match_uses_frozen_sub_ns_tolerance() -> None:
    module = _load_benchmark_module("analyze_host_device_clock_calibration.py")
    values = [Decimal("10.25"), Decimal("20.25"), Decimal("30.25")]
    portable = {"p50": "20.0", "p95": "30.0", "max": "30.75"}

    module._require_distribution_matches(
        Path("capture.db"), "marker-device residual", values, portable
    )

    material = dict(portable)
    material["max"] = "30.750001"
    with pytest.raises(ValueError, match="marker-device residual max"):
        module._require_distribution_matches(
            Path("capture.db"), "marker-device residual", values, material
        )


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


def test_overhead_pair_requires_v44_on_both_sides_and_device_target() -> None:
    module = _load_benchmark_module("analyze_npu6_clock_marker_overhead_ab.py")
    report = (
        REPO_ROOT
        / ".benchmarks/results/npu6_clock_marker_overhead_v44_l0_repeated_ab"
        / "pair_01/report/overhead_ab_summary.json"
    )
    summary = json.loads(report.read_text(encoding="utf-8"))
    disabled = copy.deepcopy(summary["disabled"])
    enabled = copy.deepcopy(summary["enabled"])

    assert all(
        module._sidecar_semantic_matching_checks(disabled, enabled).values()
    )
    assert module._calibration_meets_contract(enabled)

    disabled["sidecar"]["metadata"]["contract_version"] = (
        "idle-evidence-contract-v4.3"
    )
    assert not module._sidecar_semantic_matching_checks(disabled, enabled)[
        "sidecar_contract_version"
    ]

    enabled["sidecar"]["clock_model"]["target_clock_domain"] = "caller_host"
    assert not module._calibration_meets_contract(enabled)


def test_overhead_calibration_gate_enforces_marker_conservation() -> None:
    module = _load_benchmark_module("analyze_npu6_clock_marker_overhead_ab.py")
    report = (
        REPO_ROOT
        / ".benchmarks/results/npu6_clock_marker_overhead_v44_l0_repeated_ab"
        / "pair_01/report/overhead_ab_summary.json"
    )
    enabled = json.loads(report.read_text(encoding="utf-8"))["enabled"]
    assert module._calibration_meets_contract(enabled)

    too_few = copy.deepcopy(enabled)
    model = too_few["sidecar"]["clock_model"]
    model.update(
        input_marker_count=5,
        inlier_marker_count=5,
        rejected_marker_count=0,
        fit_marker_count=4,
        validation_marker_count=1,
        ordinal_affine_fallback_marker_count=5,
    )
    too_few["sidecar"]["marker_resolution_methods"] = {
        "ordinal_affine_fallback": 5
    }
    assert not module._calibration_meets_contract(too_few)

    inconsistent = copy.deepcopy(enabled)
    inconsistent["sidecar"]["clock_model"]["rejected_marker_count"] += 1
    assert not module._calibration_meets_contract(inconsistent)


def test_full_e4_gate_requires_positive_correlated_extent() -> None:
    module = _load_benchmark_module("analyze_npu6_clock_marker_overhead_ab.py")
    assert module._positive_e4_meets_contract({"count": 1, "duration_ns": 1})
    assert not module._positive_e4_meets_contract({"count": 0, "duration_ns": 1})
    assert not module._positive_e4_meets_contract({"count": 1, "duration_ns": 0})


def test_variant_rejects_divergent_client_duplicate_documents(tmp_path: Path) -> None:
    module = _load_benchmark_module("analyze_npu6_clock_marker_overhead_ab.py")
    source = (
        REPO_ROOT
        / ".benchmarks/results/npu6_clock_marker_overhead_v44_l0_repeated_ab"
        / "pair_01/marker_enabled"
    )
    client_dir = tmp_path / "run/client"
    client_dir.mkdir(parents=True)
    for name in ("probe_results.json", "summary.json", "run_metadata.json"):
        (client_dir / name).write_bytes((source / "run/client" / name).read_bytes())
    summary = json.loads((client_dir / "summary.json").read_text(encoding="utf-8"))
    summary["success_count"] -= 1
    (client_dir / "summary.json").write_text(
        json.dumps(summary), encoding="utf-8"
    )

    # Duplicate validation runs before profile or sidecar consumption.
    with pytest.raises(ValueError, match="summary duplicate drift"):
        module._variant(tmp_path, "select 1")


def test_accepted_overhead_markdown_cannot_emit_rejected_template_text() -> None:
    module = _load_benchmark_module("analyze_npu6_clock_marker_overhead_ab.py")
    report = (
        REPO_ROOT
        / ".benchmarks/results/npu6_clock_marker_overhead_v44_l0_repeated_ab"
        / "pair_01/report/overhead_ab_summary.json"
    )
    summary = json.loads(report.read_text(encoding="utf-8"))
    markdown = module._markdown(summary)
    assert "passes capture, protocol, calibration" in markdown
    for stale_text in (
        "invalid_input",
        "source checkout was dirty",
        "dirty source",
        "token timestamps unavailable",
        "did not preserve token-ID arrival timestamps",
    ):
        assert stale_text not in markdown

    rejected = copy.deepcopy(summary)
    rejected["protocol_valid"] = False
    rejected["protocol_acceptance"] = "FAIL"
    rejected["full_run_valid"] = False
    rejected["full_idle_evidence_acceptance"] = "FAIL"
    rejected["analysis_status"] = {
        "disabled": rejected["disabled"]["sidecar"]["metadata"][
            "analysis_status"
        ],
        "enabled": "invalid_input",
    }
    rejected["enabled"]["sidecar"]["metadata"]["analysis_status"] = (
        "invalid_input"
    )
    rejected["token_metrics_valid"] = False
    rejected["matching_checks"]["token_metrics_from_sse_token_ids"] = False
    rejected["matching_checks"]["probe_repository_clean"] = False
    rejected_markdown = module._markdown(rejected)
    assert "invalid_input" in rejected_markdown
    assert "probe repository was dirty" in rejected_markdown
    assert "token-ID arrival timestamps were unavailable" in rejected_markdown
