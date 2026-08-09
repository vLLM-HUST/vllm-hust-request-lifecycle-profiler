#!/usr/bin/env python3
"""Package lossless raw msprof inputs for the v4.4 fresh-clone audit."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import subprocess
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
DEFAULT_OUTPUT = RESULT_ROOT / "fresh_clone_inputs"
ANALYZER_REPOSITORY = "vLLM-HUST/vllm-hust-perf-analyzer"
ANALYZER_COMMIT = "9a816aaeda5d937c07d04e13901df1462d12f979"
AUDIT_SQL_PATH = "docs/report-sql/idle-evidence-audit.sql"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(REPO_ROOT.resolve()))


def _write_deterministic_gzip(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as source_stream, destination.open("wb") as raw_output:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            compresslevel=9,
            fileobj=raw_output,
            mtime=0,
        ) as compressed:
            shutil.copyfileobj(source_stream, compressed, length=1024 * 1024)


def build_bundle(
    *,
    aggregate_report: Path,
    analyzer_repo: Path,
    output_dir: Path,
) -> dict[str, Any]:
    aggregate = json.loads(aggregate_report.read_text(encoding="utf-8"))
    artifact_manifest = aggregate["artifact_manifest"]
    analyzer_head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=analyzer_repo, text=True
    ).strip()
    if analyzer_head != ANALYZER_COMMIT:
        raise ValueError(
            f"analyzer checkout is {analyzer_head}, expected {ANALYZER_COMMIT}"
        )
    audit_sql = analyzer_repo / AUDIT_SQL_PATH
    if not audit_sql.is_file():
        raise ValueError(f"missing analyzer audit SQL: {audit_sql}")

    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"output directory must be absent or empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    archived_sources: list[dict[str, Any]] = []
    direct_artifacts: list[dict[str, Any]] = []
    regenerated_artifacts: list[dict[str, Any]] = []
    by_path = {entry["path"]: entry for entry in artifact_manifest}

    for entry in artifact_manifest:
        source = RESULT_ROOT / entry["path"]
        if entry["role"] == "source_msprof_database":
            if not source.is_file():
                raise ValueError(f"missing raw msprof source: {source}")
            if source.stat().st_size != entry["size_bytes"]:
                raise ValueError(f"raw msprof size drift: {source}")
            if _sha256(source) != entry["sha256"]:
                raise ValueError(f"raw msprof hash drift: {source}")
            variant = Path(entry["path"]).parts[1]
            archive_name = (
                f"{entry['pair_id']}-{variant}-{source.name}.gz"
            )
            archive = output_dir / "raw_msprof" / archive_name
            _write_deterministic_gzip(source, archive)
            archived_sources.append(
                {
                    "archive": {
                        "compression": "gzip",
                        "path": _relative(archive),
                        "sha256": _sha256(archive),
                        "size_bytes": archive.stat().st_size,
                    },
                    "logical_source": dict(entry),
                    "pair_id": entry["pair_id"],
                    "variant": variant,
                }
            )
        elif entry["role"] == "derived_sidecar":
            variant = Path(entry["path"]).parts[1]
            source_rows = [
                row
                for row in artifact_manifest
                if row["pair_id"] == entry["pair_id"]
                and row["role"] == "source_msprof_database"
                and Path(row["path"]).parts[1] == variant
            ]
            if len(source_rows) != 1:
                raise ValueError(
                    f"{entry['path']}: expected exactly one source database"
                )
            marker_path = (
                f"{entry['pair_id']}/{variant}/run/clock_marker_brackets.tsv"
            )
            marker = by_path.get(marker_path)
            if variant == "marker_enabled" and marker is None:
                raise ValueError(f"missing marker input for {entry['path']}")
            regenerated_artifacts.append(
                {
                    "expected_derived_sidecar": dict(entry),
                    "marker_input": dict(marker) if marker is not None else None,
                    "pair_id": entry["pair_id"],
                    "source_msprof_path": source_rows[0]["path"],
                    "variant": variant,
                }
            )
        else:
            if not source.is_file():
                raise ValueError(f"missing directly committed artifact: {source}")
            if source.stat().st_size != entry["size_bytes"]:
                raise ValueError(f"direct artifact size drift: {source}")
            if _sha256(source) != entry["sha256"]:
                raise ValueError(f"direct artifact hash drift: {source}")
            direct_artifacts.append(dict(entry))

    report_entries = [
        {
            "path": entry["path"],
            "sha256": entry["sha256"],
            "size_bytes": entry["size_bytes"],
        }
        for entry in artifact_manifest
        if entry["role"] == "pair_acceptance_report"
    ]
    bundle = {
        "analyzer": {
            "audit_sql_path": AUDIT_SQL_PATH,
            "audit_sql_sha256": _sha256(audit_sql),
            "audit_sql_size_bytes": audit_sql.stat().st_size,
            "commit": ANALYZER_COMMIT,
            "repository": ANALYZER_REPOSITORY,
        },
        "artifact_coverage": {
            "archived_lossless_raw_source_count": len(archived_sources),
            "direct_committed_artifact_count": len(direct_artifacts),
            "regenerated_derived_sidecar_count": len(regenerated_artifacts),
            "source_artifact_count": len(artifact_manifest),
            "uncovered_artifact_count": 0,
        },
        "archived_raw_sources": archived_sources,
        "direct_artifacts": direct_artifacts,
        "evidence_label": "real-online fresh-clone audit inputs",
        "regenerated_artifacts": regenerated_artifacts,
        "report_entries": report_entries,
        "schema_version": "idle-evidence-fresh-clone-bundle-v1",
        "source_artifact_manifest": artifact_manifest,
        "source_artifact_manifest_sha256": _canonical_sha256(
            artifact_manifest
        ),
        "source_result_root": str(RESULT_ROOT.relative_to(REPO_ROOT)),
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(bundle, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aggregate-report", type=Path, default=AGGREGATE_REPORT)
    parser.add_argument(
        "--analyzer-repo",
        type=Path,
        default=REPO_ROOT.parent / "vllm-hust-perf-analyzer",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    bundle = build_bundle(
        aggregate_report=args.aggregate_report,
        analyzer_repo=args.analyzer_repo,
        output_dir=args.output_dir,
    )
    print(
        json.dumps(
            {
                "archive_count": len(bundle["archived_raw_sources"]),
                "output_dir": _relative(args.output_dir),
                "source_artifact_count": bundle["artifact_coverage"][
                    "source_artifact_count"
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
