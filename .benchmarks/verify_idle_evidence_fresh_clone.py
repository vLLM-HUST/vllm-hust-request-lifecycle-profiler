#!/usr/bin/env python3
"""Reproduce v4.4 acceptance from lossless raw inputs in a fresh clone."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import shutil
import sqlite3
import subprocess
import tempfile
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
CROSS_CLOCK_COUNTERS = (
    "cross_clock_fail_closed_errors",
    "host_evidence_source_errors",
    "host_explanation_contract_errors",
    "queued_task_link_errors",
)


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


def _load_pair_analyzer() -> Any:
    spec = importlib.util.spec_from_file_location("pair_analyzer", PAIR_ANALYZER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {PAIR_ANALYZER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
        "direct_committed_artifact_count": 45,
        "regenerated_derived_sidecar_count": 6,
        "source_artifact_count": 57,
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
    pair_analyzer = _load_pair_analyzer()
    with tempfile.TemporaryDirectory(prefix="idle-evidence-fresh-clone-") as tmp:
        extraction_root = Path(tmp)
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
            generated = extraction_root / pair_id / variant / "traceloom_sidecar.db"
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
                "2",
            ]
            marker = entry["marker_input"]
            if marker is not None:
                command.extend(
                    [
                        "--clock-marker-brackets",
                        str((RESULT_ROOT / marker["path"]).resolve()),
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
            if observed != expected:
                raise ValueError(
                    f"{pair_id}/{variant}: regenerated sidecar semantics drift"
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
            generated.unlink()

    return {
        "accepted_report_count": 3,
        "archived_raw_source_count": len(archived_by_source),
        "cross_clock_audit_counter_errors": 0,
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
