#!/usr/bin/env python3
"""Reproduce v4.4 acceptance from lossless raw inputs in a fresh clone."""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import importlib.util
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULT_ROOT = (
    REPO_ROOT
    / ".benchmarks/results/npu6_clock_marker_overhead_v44_l0_repeated_ab"
)
AGGREGATE_REPORT = (
    RESULT_ROOT / "aggregate_report_final_v2/repeated_overhead_ab_summary.json"
)
BUNDLE_MANIFEST = RESULT_ROOT / "fresh_clone_inputs/manifest.json"
PAIR_ANALYZER = REPO_ROOT / ".benchmarks/analyze_npu6_clock_marker_overhead_ab.py"
REPEATED_ANALYZER = (
    REPO_ROOT / ".benchmarks/analyze_repeated_clock_marker_overhead_ab.py"
)
CALIBRATION_ANALYZER = (
    REPO_ROOT / ".benchmarks/analyze_host_device_clock_calibration.py"
)
CALIBRATION_ROOT = (
    REPO_ROOT / ".benchmarks/results/npu6_host_device_clock_calibration"
)
CALIBRATION_MANIFEST = CALIBRATION_ROOT / "audit_inputs_manifest.json"
CALIBRATION_SUMMARY = CALIBRATION_ROOT / "calibration_summary.json"
CROSS_CLOCK_COUNTERS = (
    "cross_clock_fail_closed_errors",
    "host_evidence_source_errors",
    "host_explanation_contract_errors",
    "queued_task_link_errors",
)
PORTABLE_FLOAT_NS_TOLERANCE = Decimal("0.5")
PORTABLE_FLOAT_PPM_TOLERANCE = Decimal("0.000001")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_analyzer(path: Path, module_name: str) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_pair_analyzer() -> Any:
    return _load_analyzer(PAIR_ANALYZER, "pair_analyzer")


def _safe_repo_path(relative: str) -> Path:
    path = (REPO_ROOT / relative).resolve()
    path.relative_to(REPO_ROOT.resolve())
    return path


def _assert_file(path: Path, *, sha256: str, size_bytes: int) -> None:
    if not path.is_file():
        raise ValueError(f"missing artifact: {path}")
    if path.stat().st_size != size_bytes:
        raise ValueError(f"size mismatch: {path}")
    if _sha256(path) != sha256:
        raise ValueError(f"sha256 mismatch: {path}")


def _normalize_audit(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    result.pop("run_id", None)
    return result


def _normalize_model(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    result.pop("run_id", None)
    result.pop("clock_model_id", None)
    return result


def _normalize_pair_report(report: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(report)
    result["enabled_calibration"] = _normalize_model(
        result["enabled_calibration"]
    )
    for variant in ("disabled", "enabled"):
        row = result[variant]
        row.pop("profile_db", None)
        row.pop("variant_dir", None)
        sidecar = row["sidecar"]
        sidecar.pop("sidecar_path", None)
        sidecar["audit"] = _normalize_audit(sidecar["audit"])
        sidecar["clock_model"] = _normalize_model(sidecar["clock_model"])
        metadata = sidecar["metadata"]
        for field in ("metadata_json", "run_id", "source_path"):
            metadata.pop(field, None)
    for diagnostic in result.get("excluded_diagnostics", []):
        diagnostic.pop("variant_dir", None)
    return result


def _normalize_aggregate_report(report: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(report)
    result.pop("artifact_manifest", None)
    return result


def _normalize_calibration_report(report: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(report)
    for capture in result["captures"]:
        capture.pop("sidecar_path", None)
        capture.pop("run_id", None)
        capture.pop("clock_model_id", None)
    return result


def _require_unique_calibration_inputs(manifest: dict[str, Any]) -> None:
    for artifact_name in ("source_msprof_db", "clock_marker_brackets"):
        digests = [
            capture["artifacts"][artifact_name]["sha256"]
            for capture in manifest["captures"]
        ]
        if len(set(digests)) != len(digests):
            raise ValueError(
                f"calibration captures reuse {artifact_name} content identity"
            )


def _assert_layered_result_surface() -> None:
    tracked = set(
        subprocess.check_output(
            ["git", "ls-files", ".benchmarks/results"],
            cwd=REPO_ROOT,
            text=True,
        ).splitlines()
    )
    forbidden_prefixes = (
        ".benchmarks/results/npu6_clock_marker_l2_validity_probe/",
        ".benchmarks/results/npu6_clock_marker_overhead_fixed_rate_ab/",
        ".benchmarks/results/npu6_clock_marker_overhead_v44_fixed_rate_ab/",
        ".benchmarks/results/npu6_host_device_clock_calibration/"
        "capture_02_real_calibrated/",
        ".benchmarks/results/npu6_host_device_clock_calibration/"
        "capture_03_real_calibrated/",
        ".benchmarks/results/npu6_host_device_clock_calibration/"
        "capture_04_real_calibrated/",
    )
    redundant_names = (
        "/traceloom_result",
        "/traceloom_sidecar",
        "/loop_tree",
    )
    violations = sorted(
        path
        for path in tracked
        if path.startswith(forbidden_prefixes)
        or (
            path.startswith(str(CALIBRATION_ROOT.relative_to(REPO_ROOT)) + "/")
            and any(name in path for name in redundant_names)
        )
        or (
            path.startswith(str(RESULT_ROOT.relative_to(REPO_ROOT)) + "/pair_")
            and "/traceloom_result" in path
        )
    )
    if violations:
        raise ValueError(
            "benchmark result layer contains obsolete or reproducible derived "
            f"artifacts: {violations}"
        )


def verify_calibration_sources(
    *, manifest_path: Path = CALIBRATION_MANIFEST
) -> dict[str, Any]:
    manifest = _load_json(manifest_path)
    if manifest["schema_version"] != 2:
        raise ValueError("unsupported calibration audit manifest")
    if len(manifest["captures"]) != 3:
        raise ValueError("calibration audit requires exactly three captures")
    _require_unique_calibration_inputs(manifest)
    for capture in manifest["captures"]:
        artifacts = capture["artifacts"]
        if set(artifacts) != {
            "clock_marker_brackets",
            "probe_summary",
            "source_msprof_db",
        }:
            raise ValueError(
                f"{capture['name']}: calibration manifest contains derived input"
            )
        for artifact in artifacts.values():
            _assert_file(
                _safe_repo_path(artifact["path"]),
                sha256=artifact["sha256"],
                size_bytes=artifact["size_bytes"],
            )
    for artifact in manifest["summary_artifacts"].values():
        _assert_file(
            _safe_repo_path(artifact["path"]),
            sha256=artifact["sha256"],
            size_bytes=artifact["size_bytes"],
        )
    return manifest


def _portable_numeric_tolerance(path: str) -> Decimal | None:
    components = path.replace("[", ".").replace("]", "").split(".")
    if any(component.endswith("_ns") for component in components):
        return PORTABLE_FLOAT_NS_TOLERANCE
    if any(component.endswith("_ppm") for component in components):
        return PORTABLE_FLOAT_PPM_TOLERANCE
    return None


def _portable_decimal(value: Any) -> Decimal | None:
    if isinstance(value, float):
        result = Decimal(str(value))
    elif isinstance(value, str):
        try:
            result = Decimal(value)
        except InvalidOperation:
            return None
    else:
        return None
    return result if result.is_finite() else None


def _portable_numeric_match(expected: Any, observed: Any, path: str) -> bool:
    tolerance = _portable_numeric_tolerance(path)
    if tolerance is None or type(expected) is not type(observed):
        return False
    expected_decimal = _portable_decimal(expected)
    observed_decimal = _portable_decimal(observed)
    return (
        expected_decimal is not None
        and observed_decimal is not None
        and abs(expected_decimal - observed_decimal) <= tolerance
    )


def _first_difference(expected: Any, observed: Any, path: str = "$") -> str:
    if type(expected) is not type(observed):
        return (
            f"{path}: expected type {type(expected).__name__}, "
            f"observed {type(observed).__name__}"
        )
    if isinstance(expected, dict):
        expected_keys = set(expected)
        observed_keys = set(observed)
        if expected_keys != observed_keys:
            return (
                f"{path}: missing={sorted(expected_keys - observed_keys)}, "
                f"extra={sorted(observed_keys - expected_keys)}"
            )
        for key in sorted(expected):
            difference = _first_difference(
                expected[key], observed[key], f"{path}.{key}"
            )
            if difference:
                return difference
        return ""
    if isinstance(expected, list):
        if len(expected) != len(observed):
            return f"{path}: expected length {len(expected)}, observed {len(observed)}"
        for index, (expected_item, observed_item) in enumerate(
            zip(expected, observed)
        ):
            difference = _first_difference(
                expected_item, observed_item, f"{path}[{index}]"
            )
            if difference:
                return difference
        return ""
    if _portable_numeric_match(expected, observed, path):
        return ""
    if expected != observed:
        return f"{path}: expected {expected!r}, observed {observed!r}"
    return ""


def _require_same_semantics(label: str, expected: Any, observed: Any) -> None:
    difference = _first_difference(expected, observed)
    if difference:
        raise ValueError(f"{label}: {difference}")


def _portable_projection(expected: Any, observed: Any, path: str = "$") -> Any:
    """Project tolerated diagnostics onto accepted values for Markdown checks."""
    if type(expected) is not type(observed):
        return copy.deepcopy(observed)
    if isinstance(expected, dict):
        if set(expected) != set(observed):
            return copy.deepcopy(observed)
        return {
            key: _portable_projection(
                expected[key], observed[key], f"{path}.{key}"
            )
            for key in expected
        }
    if isinstance(expected, list):
        if len(expected) != len(observed):
            return copy.deepcopy(observed)
        return [
            _portable_projection(expected_item, observed_item, f"{path}[{index}]")
            for index, (expected_item, observed_item) in enumerate(
                zip(expected, observed)
            )
        ]
    if _portable_numeric_match(expected, observed, path):
        return copy.deepcopy(expected)
    return copy.deepcopy(observed)


def _rows_by_key(
    connection: sqlite3.Connection, query: str, key: str
) -> dict[str, dict[str, Any]]:
    return {str(row[key]): dict(row) for row in connection.execute(query)}


def _sidecar_semantics(path: Path, audit_sql: str) -> dict[str, Any]:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        integrity = connection.execute("pragma integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError(f"{path}: sqlite integrity_check={integrity}")
        model_rows = connection.execute(
            "select * from traceloom_clock_model order by device_id"
        ).fetchall()
        if len(model_rows) != 1:
            raise ValueError(f"{path}: expected exactly one clock model")
        metadata = dict(
            connection.execute("select * from traceloom_run_metadata").fetchone()
        )
        audit_rows = connection.execute(audit_sql).fetchall()
        if len(audit_rows) != 1:
            raise ValueError(f"{path}: expected exactly one audit row")
        categories = {
            f"{row['category']}:{row['evidence_level']}:{row['evidence_relation']}": dict(
                row
            )
            for row in connection.execute(
                "select category, evidence_level, evidence_relation, "
                "count(*) as count, sum(duration_ns) as duration_ns "
                "from traceloom_idle_explanation "
                "group by category, evidence_level, evidence_relation"
            )
        }
        return {
            "audit": _normalize_audit(dict(audit_rows[0])),
            "categories": categories,
            "clock_model": _normalize_model(dict(model_rows[0])),
            "device_intervals": _rows_by_key(
                connection,
                "select interval_kind, count(*) as count, "
                "sum(duration_ns) as duration_ns "
                "from traceloom_device_interval group by interval_kind",
                "interval_kind",
            ),
            "evidence_levels": _rows_by_key(
                connection,
                "select evidence_level, count(*) as count, "
                "sum(duration_ns) as duration_ns "
                "from traceloom_idle_explanation group by evidence_level",
                "evidence_level",
            ),
            "marker_resolution_methods": {
                str(row["resolution_method"]): int(row["count"])
                for row in connection.execute(
                    "select resolution_method, count(*) as count "
                    "from traceloom_clock_marker group by resolution_method"
                )
            },
            "marker_states": {
                str(row["marker_state"]): int(row["count"])
                for row in connection.execute(
                    "select marker_state, count(*) as count "
                    "from traceloom_clock_marker group by marker_state"
                )
            },
            "metadata": {
                key: metadata[key]
                for key in (
                    "analysis_status",
                    "attribution_rule_version",
                    "collection_status",
                    "contract_version",
                    "db_idx",
                    "source_kind",
                )
            },
        }
    finally:
        connection.close()


def _expected_semantics(summary: dict[str, Any], variant: str) -> dict[str, Any]:
    expected = summary["disabled" if variant == "marker_disabled" else "enabled"]
    sidecar = expected["sidecar"]
    metadata = sidecar["metadata"]
    return {
        "audit": _normalize_audit(sidecar["audit"]),
        "categories": sidecar["categories"],
        "clock_model": _normalize_model(sidecar["clock_model"]),
        "device_intervals": sidecar["device_intervals"],
        "evidence_levels": sidecar["evidence_levels"],
        "marker_resolution_methods": sidecar["marker_resolution_methods"],
        "marker_states": sidecar["marker_states"],
        "metadata": {
            key: metadata[key]
            for key in (
                "analysis_status",
                "attribution_rule_version",
                "collection_status",
                "contract_version",
                "db_idx",
                "source_kind",
            )
        },
    }


def verify_static_bundle(
    *, manifest_path: Path = BUNDLE_MANIFEST
) -> tuple[dict[str, Any], dict[str, Any]]:
    _assert_layered_result_surface()
    bundle = _load_json(manifest_path)
    aggregate = _load_json(AGGREGATE_REPORT)
    artifact_manifest = aggregate["artifact_manifest"]
    if bundle["source_artifact_manifest"] != artifact_manifest:
        raise ValueError("source artifact manifest contents mismatch")
    if bundle["source_artifact_manifest_sha256"] != _canonical_sha256(
        bundle["source_artifact_manifest"]
    ):
        raise ValueError("source artifact manifest digest mismatch")
    coverage = bundle["artifact_coverage"]
    if coverage != {
        "archived_lossless_raw_source_count": 6,
        "direct_committed_artifact_count": 39,
        "regenerated_derived_sidecar_count": 6,
        "source_artifact_count": 51,
        "uncovered_artifact_count": 0,
    }:
        raise ValueError(f"unexpected artifact coverage: {coverage}")
    for entry in bundle["direct_artifacts"]:
        _assert_file(
            RESULT_ROOT / entry["path"],
            sha256=entry["sha256"],
            size_bytes=entry["size_bytes"],
        )
    for entry in bundle["archived_raw_sources"]:
        archive = entry["archive"]
        _assert_file(
            _safe_repo_path(archive["path"]),
            sha256=archive["sha256"],
            size_bytes=archive["size_bytes"],
        )
    analyzer = _load_pair_analyzer()
    stale_text = (
        "invalid_input",
        "source checkout was dirty",
        "dirty source",
        "token timestamps unavailable",
        "did not preserve token-ID arrival timestamps",
    )
    for pair_id in aggregate["pair_ids"]:
        json_path = RESULT_ROOT / pair_id / "report/overhead_ab_summary.json"
        markdown_path = RESULT_ROOT / pair_id / "report/overhead_ab_summary.md"
        summary = _load_json(json_path)
        for field in (
            "capture_acceptance",
            "protocol_acceptance",
            "calibration_acceptance",
            "full_idle_evidence_acceptance",
        ):
            if summary[field] != "PASS":
                raise ValueError(f"{json_path}: {field} is not PASS")
        if summary["analysis_status"] != {"disabled": "ok", "enabled": "ok"}:
            raise ValueError(f"{json_path}: analysis status is not accepted")
        if summary["token_metrics_valid"] is not True:
            raise ValueError(f"{json_path}: token metrics are not valid")
        markdown = markdown_path.read_text(encoding="utf-8")
        if analyzer._markdown(summary) != markdown:
            raise ValueError(f"{markdown_path}: generator output drift")
        for text in stale_text:
            if text in markdown:
                raise ValueError(f"{markdown_path}: stale rejection text {text!r}")
    return bundle, aggregate


def _recompute_calibration(
    *,
    analyzer_repo: Path,
    traceloom: Path,
    audit_path: Path,
    output_root: Path,
) -> int:
    manifest = verify_calibration_sources()
    if manifest["analyzer"]["commit"] != subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=analyzer_repo, text=True
    ).strip():
        raise ValueError("calibration manifest analyzer commit mismatch")
    sidecars: list[Path] = []
    for capture in manifest["captures"]:
        artifacts = capture["artifacts"]
        sidecar = (
            output_root
            / capture["name"]
            / "traceloom_sidecar_v44_recomputed.db"
        )
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        _run_checked(
            [
                str(traceloom.resolve()),
                "--source-db",
                artifacts["source_msprof_db"]["path"],
                "--source-kind",
                "ascend_sqlite_hot_path",
                "--clock-marker-brackets",
                artifacts["clock_marker_brackets"]["path"],
                "--compat-db-out",
                str(sidecar),
                "--sidecar-only",
                "--threads",
                "1",
            ],
            cwd=REPO_ROOT,
            label=f"calibration sidecar regeneration for {capture['name']}",
        )
        sidecars.append(sidecar)

    report_dir = output_root / "summary"
    command = [
        sys.executable,
        str(CALIBRATION_ANALYZER),
    ]
    for sidecar in sidecars:
        command.extend(["--sidecar", str(sidecar)])
    command.extend(
        [
            "--output-dir",
            str(report_dir),
            "--require-three",
            "--audit-sql",
            str(audit_path.resolve()),
        ]
    )
    _run_checked(
        command,
        cwd=REPO_ROOT,
        label="calibration summary recomputation",
    )
    expected = _load_json(CALIBRATION_SUMMARY)
    observed = _load_json(report_dir / "calibration_summary.json")
    difference = _first_difference(
        _normalize_calibration_report(expected),
        _normalize_calibration_report(observed),
    )
    if difference:
        raise ValueError("recomputed calibration report drift: " + difference)
    expected_markdown = CALIBRATION_SUMMARY.with_suffix(".md").read_text(
        encoding="utf-8"
    )
    observed_markdown = (report_dir / "calibration_summary.md").read_text(
        encoding="utf-8"
    )
    calibration_analyzer = _load_analyzer(
        CALIBRATION_ANALYZER, "calibration_analyzer"
    )
    if observed_markdown != calibration_analyzer._markdown(observed):
        raise ValueError("recomputed calibration Markdown is internally inconsistent")
    portable_markdown = calibration_analyzer._markdown(
        _portable_projection(expected, observed)
    )
    if portable_markdown != expected_markdown:
        raise ValueError("recomputed calibration Markdown semantic drift")
    return len(sidecars)


def _run_checked(command: list[str], *, cwd: Path, label: str) -> None:
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"{label} failed with exit code {completed.returncode}:\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )


def verify_fresh_clone(
    *,
    analyzer_repo: Path,
    traceloom: Path,
    manifest_path: Path = BUNDLE_MANIFEST,
) -> dict[str, Any]:
    bundle, _ = verify_static_bundle(manifest_path=manifest_path)
    analyzer = bundle["analyzer"]
    analyzer_head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=analyzer_repo, text=True
    ).strip()
    if analyzer_head != analyzer["commit"]:
        raise ValueError(
            f"analyzer checkout is {analyzer_head}, expected {analyzer['commit']}"
        )
    audit_path = analyzer_repo / analyzer["audit_sql_path"]
    _assert_file(
        audit_path,
        sha256=analyzer["audit_sql_sha256"],
        size_bytes=analyzer["audit_sql_size_bytes"],
    )
    audit_sql = audit_path.read_text(encoding="utf-8")

    archived_by_source = {
        entry["logical_source"]["path"]: entry
        for entry in bundle["archived_raw_sources"]
    }
    pair_summaries = {
        pair_id: _load_json(
            RESULT_ROOT / pair_id / "report/overhead_ab_summary.json"
        )
        for pair_id in ("pair_01", "pair_02", "pair_03")
    }
    regenerated_count = 0
    recomputed_pair_count = 0
    pair_analyzer = _load_pair_analyzer()
    with tempfile.TemporaryDirectory(prefix="idle-evidence-fresh-clone-") as tmp:
        extraction_root = Path(tmp)
        for entry in bundle["direct_artifacts"]:
            if entry["role"] == "pair_acceptance_report":
                continue
            source = RESULT_ROOT / entry["path"]
            destination = extraction_root / entry["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        for logical_path, entry in archived_by_source.items():
            archive_path = _safe_repo_path(entry["archive"]["path"])
            output_path = extraction_root / logical_path
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(archive_path, "rb") as compressed, output_path.open(
                "wb"
            ) as output:
                shutil.copyfileobj(compressed, output, length=1024 * 1024)
            logical = entry["logical_source"]
            _assert_file(
                output_path,
                sha256=logical["sha256"],
                size_bytes=logical["size_bytes"],
            )

        for entry in bundle["regenerated_artifacts"]:
            pair_id = entry["pair_id"]
            variant = entry["variant"]
            source_path = entry["source_msprof_path"]
            generated = extraction_root / entry["expected_derived_sidecar"][
                "path"
            ]
            generated.parent.mkdir(parents=True, exist_ok=True)
            command = [
                str(traceloom.resolve()),
                "--source-db",
                source_path,
                "--source-kind",
                "ascend_sqlite_hot_path",
                "--compat-db-out",
                str(generated),
                "--sidecar-only",
                "--threads",
                "1",
            ]
            marker = entry["marker_input"]
            if marker is not None:
                command.extend(
                    [
                        "--clock-marker-brackets",
                        str((extraction_root / marker["path"]).resolve()),
                    ]
                )
            completed = subprocess.run(
                command,
                cwd=extraction_root,
                check=False,
                capture_output=True,
                text=True,
            )
            if completed.returncode != 0:
                raise RuntimeError(
                    f"sidecar regeneration failed for {pair_id}/{variant}:\n"
                    f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
                )
            observed = _sidecar_semantics(generated, audit_sql)
            expected = _expected_semantics(pair_summaries[pair_id], variant)
            _require_same_semantics(
                f"{pair_id}/{variant}: regenerated sidecar semantics drift",
                expected,
                observed,
            )
            audit = observed["audit"]
            if audit["audit_status"] != "PASS":
                raise ValueError(f"{pair_id}/{variant}: SQL audit did not pass")
            if any(int(audit[name]) != 0 for name in CROSS_CLOCK_COUNTERS):
                raise ValueError(
                    f"{pair_id}/{variant}: nonzero cross-clock audit counter"
                )
            task_diagnostics = pair_analyzer._task_duration_diagnostics(
                extraction_root / source_path
            )
            summary_key = "disabled" if variant == "marker_disabled" else "enabled"
            if task_diagnostics != pair_summaries[pair_id][summary_key][
                "task_duration_diagnostics"
            ]:
                raise ValueError(f"{pair_id}/{variant}: TASK diagnostics drift")
            regenerated_count += 1

        for pair_id, expected in pair_summaries.items():
            pair_root = extraction_root / pair_id
            report_dir = pair_root / "report"
            _run_checked(
                [
                    sys.executable,
                    str(PAIR_ANALYZER),
                    "--disabled-dir",
                    str(pair_root / "marker_disabled"),
                    "--enabled-dir",
                    str(pair_root / "marker_enabled"),
                    "--output-dir",
                    str(report_dir),
                    "--audit-sql",
                    str(audit_path.resolve()),
                ],
                cwd=extraction_root,
                label=f"pair report recomputation for {pair_id}",
            )
            observed_report = _load_json(report_dir / "overhead_ab_summary.json")
            normalized_expected = _normalize_pair_report(expected)
            normalized_observed = _normalize_pair_report(observed_report)
            difference = _first_difference(
                normalized_expected, normalized_observed
            )
            if difference:
                raise ValueError(
                    f"{pair_id}: recomputed pair report drift: {difference}"
                )
            observed_markdown = (
                report_dir / "overhead_ab_summary.md"
            ).read_text(encoding="utf-8")
            expected_markdown = (
                RESULT_ROOT / pair_id / "report/overhead_ab_summary.md"
            ).read_text(encoding="utf-8")
            if observed_markdown != pair_analyzer._markdown(observed_report):
                raise ValueError(
                    f"{pair_id}: recomputed pair Markdown is internally inconsistent"
                )
            portable_markdown = pair_analyzer._markdown(
                _portable_projection(expected, observed_report)
            )
            if portable_markdown != expected_markdown:
                raise ValueError(f"{pair_id}: recomputed pair Markdown semantic drift")
            recomputed_pair_count += 1

        aggregate_dir = extraction_root / "aggregate_report"
        _run_checked(
            [
                sys.executable,
                str(REPEATED_ANALYZER),
                "--root",
                str(extraction_root),
                "--output-dir",
                str(aggregate_dir),
            ],
            cwd=extraction_root,
            label="aggregate report recomputation",
        )
        observed_aggregate = _load_json(
            aggregate_dir / "repeated_overhead_ab_summary.json"
        )
        expected_aggregate = _load_json(AGGREGATE_REPORT)
        aggregate_difference = _first_difference(
            _normalize_aggregate_report(expected_aggregate),
            _normalize_aggregate_report(observed_aggregate),
        )
        if aggregate_difference:
            raise ValueError(
                "recomputed aggregate report drift: " + aggregate_difference
            )
        observed_aggregate_markdown = (
            aggregate_dir / "repeated_overhead_ab_summary.md"
        ).read_text(encoding="utf-8")
        expected_aggregate_markdown = AGGREGATE_REPORT.with_suffix(
            ".md"
        ).read_text(encoding="utf-8")
        repeated_analyzer = _load_analyzer(
            REPEATED_ANALYZER, "repeated_analyzer"
        )
        if observed_aggregate_markdown != repeated_analyzer._markdown(
            observed_aggregate
        ):
            raise ValueError(
                "recomputed aggregate Markdown is internally inconsistent"
            )
        portable_aggregate_markdown = repeated_analyzer._markdown(
            _portable_projection(expected_aggregate, observed_aggregate)
        )
        if portable_aggregate_markdown != expected_aggregate_markdown:
            raise ValueError("recomputed aggregate Markdown semantic drift")

        calibration_count = _recompute_calibration(
            analyzer_repo=analyzer_repo,
            traceloom=traceloom,
            audit_path=audit_path,
            output_root=extraction_root / "calibration",
        )

    return {
        "accepted_report_count": recomputed_pair_count,
        "aggregate_report_recomputed": True,
        "archived_raw_source_count": len(archived_by_source),
        "calibration_sidecar_count": calibration_count,
        "calibration_summary_recomputed": True,
        "cross_clock_audit_counter_errors": 0,
        "recomputed_pair_report_count": recomputed_pair_count,
        "regenerated_sidecar_count": regenerated_count,
        "status": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--analyzer-repo", type=Path, required=True)
    parser.add_argument("--traceloom", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=BUNDLE_MANIFEST)
    args = parser.parse_args()
    result = verify_fresh_clone(
        analyzer_repo=args.analyzer_repo,
        traceloom=args.traceloom,
        manifest_path=args.manifest,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
