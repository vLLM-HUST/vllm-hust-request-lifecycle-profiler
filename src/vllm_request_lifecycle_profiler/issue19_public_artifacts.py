"""Deterministic public export for the Issue #19 matched M0 evidence.

The execution-node artifacts remain the source of truth.  This module creates
the smaller public view required for review: structured mechanism evidence is
retained, machine topology is replaced by stable placeholders, and raw server
logs plus full ``npu-smi`` snapshots stay in local custody.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SANITIZER_VERSION = "issue19-public-sanitizer/v1"
PUBLIC_SCHEMA = "issue19-public-evidence/v1"
WITHHELD_NAMES = frozenset(
    {"server.log", "npu_before.txt", "npu_during.txt", "npu_after.txt"}
)
DERIVED_NAMES = frozenset({"summary.json", "redaction_manifest.json"})
PID_KEYS = frozenset(
    {
        "api_pid",
        "engine_pid",
        "pid",
        "ppid",
        "target_pid",
        "worker_pid",
    }
)
DEVICE_KEYS = frozenset({"device", "device_id", "npu_device"})
PORT_KEYS = frozenset({"port", "service_port"})
PRIVATE_IPV4_RE = re.compile(
    r"\b(?:127\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"
)
PCI_RE = re.compile(r"\b[0-9A-Fa-f]{4}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}\.[0-7]\b")
ABSOLUTE_HOST_PATH_RE = re.compile(
    r"(?<![\w$])/(?:root|home|tmp|dev)/(?:[^\s\"'`,;:)\]}]+)"
)
WORKTREE_RE = re.compile(r"/root/vllm-request-lifecycle-profiler-plugin-issue19-m0")
MODEL_RE = re.compile(
    r"/root/\.cache/huggingface/"
    r"hub/models--Qwen--Qwen2\.5-14B-Instruct/snapshots/[0-9a-f]+"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _iter_json_values(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key, child
            yield from _iter_json_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_json_values(child)


def _read_structured(path: Path) -> list[Any]:
    if path.suffix == ".json":
        return [json.loads(path.read_text(encoding="utf-8"))]
    if path.suffix == ".jsonl":
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    return []


@dataclass
class Redactor:
    pids: dict[str, str] = field(default_factory=dict)
    ports: dict[str, str] = field(default_factory=dict)
    devices: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_source(cls, source_root: Path) -> Redactor:
        pid_values: set[str] = set()
        port_values: set[str] = set()
        device_values: set[str] = set()
        for path in sorted(source_root.rglob("*")):
            if not path.is_file() or path.name in WITHHELD_NAMES:
                continue
            for document in _read_structured(path):
                for key, value in _iter_json_values(document):
                    if key in PID_KEYS and isinstance(value, int):
                        pid_values.add(str(value))
                    elif key in PORT_KEYS and isinstance(value, (int, str)):
                        port_values.add(str(value))
                    elif key in DEVICE_KEYS and isinstance(value, (int, str)):
                        device_values.add(str(value))
            for part in path.parts:
                match = re.fullmatch(r"(\d+)\.pending-transfer(?:-arm|\.json)", part)
                if match:
                    pid_values.add(match.group(1))
        return cls(
            pids={
                value: f"PID_{index:03d}"
                for index, value in enumerate(sorted(pid_values, key=int), start=1)
            },
            ports={value: "SERVICE_PORT" for value in sorted(port_values)},
            devices={value: "NPU_TARGET" for value in sorted(device_values)},
        )

    def text(self, value: str) -> str:
        result = MODEL_RE.sub("$MODEL_DIR", value)
        result = WORKTREE_RE.sub("$WORKTREE", result)
        result = PRIVATE_IPV4_RE.sub("$PRIVATE_HOST", result)
        result = PCI_RE.sub("$PCI_DEVICE", result)
        for original, replacement in sorted(
            self.pids.items(), key=lambda item: len(item[0]), reverse=True
        ):
            result = re.sub(rf"(?<!\d){re.escape(original)}(?!\d)", replacement, result)
        for original, replacement in self.ports.items():
            result = re.sub(rf"(?<!\d){re.escape(original)}(?!\d)", replacement, result)
        for original, replacement in self.devices.items():
            result = re.sub(
                rf"(?i)(\b(?:npu|device)[ _:=#-]*){re.escape(original)}\b",
                rf"\1{replacement}",
                result,
            )
        return ABSOLUTE_HOST_PATH_RE.sub("$HOST_PATH", result)

    def value(self, value: Any, *, key: str | None = None) -> Any:
        if key in PID_KEYS and isinstance(value, int):
            return self.pids[str(value)]
        if key in PORT_KEYS and isinstance(value, (int, str)):
            return self.ports[str(value)]
        if key in DEVICE_KEYS and isinstance(value, (int, str)):
            return self.devices[str(value)]
        if isinstance(value, dict):
            return {
                child_key: self.value(child, key=child_key)
                for child_key, child in value.items()
            }
        if isinstance(value, list):
            return [self.value(child) for child in value]
        if isinstance(value, str):
            return self.text(value)
        return value

    def relative_path(self, path: Path) -> Path:
        return Path(*(self.text(part) for part in path.parts))


def _paired_latency(fault: dict[str, Any], control: dict[str, Any]) -> dict[str, Any]:
    fault_p99 = fault["distribution"]["unaffected_survivor_p99_seconds"]
    control_p99 = control["distribution"]["unaffected_survivor_p99_seconds"]
    comparable = (
        fault.get("evidence_valid") is True
        and control.get("evidence_valid") is True
        and isinstance(fault_p99, (int, float))
        and isinstance(control_p99, (int, float))
        and control_p99 > 0
        and fault["distribution"].get("unaffected_survivor_count") == 58
        and control["distribution"].get("unaffected_survivor_count") == 58
    )
    if not comparable:
        return {
            "evaluable": False,
            "observed": None,
            "reason": "matched_normal_control_incomplete",
        }
    relative_delta = (float(fault_p99) - float(control_p99)) / float(control_p99)
    boundary_deltas: dict[str, float] = {}
    for name, fault_row in fault["lifecycle_boundary_p99_seconds"].items():
        control_row = control["lifecycle_boundary_p99_seconds"].get(name, {})
        fault_value = fault_row.get("p99")
        control_value = control_row.get("p99")
        if isinstance(fault_value, (int, float)) and isinstance(
            control_value, (int, float)
        ):
            boundary_deltas[name] = float(fault_value) - float(control_value)
    positive = sorted(
        ((delta, name) for name, delta in boundary_deltas.items() if delta > 0),
        reverse=True,
    )
    top1_boundary = positive[0][1] if positive else None
    if relative_delta >= 0.10 and top1_boundary is None:
        return {
            "evaluable": False,
            "observed": None,
            "reason": "p99_threshold_crossed_without_graph_top1",
            "fault_p99_seconds": fault_p99,
            "normal_control_p99_seconds": control_p99,
            "relative_delta": relative_delta,
            "boundary_p99_delta_seconds": boundary_deltas,
        }
    return {
        "evaluable": True,
        "observed": relative_delta >= 0.10,
        "reason": None,
        "fault_p99_seconds": fault_p99,
        "normal_control_p99_seconds": control_p99,
        "relative_delta": relative_delta,
        "top1_boundary": top1_boundary,
        "boundary_p99_delta_seconds": boundary_deltas,
    }


def recompute_summary(public_root: Path) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for index in range(10):
        fault_dirs = sorted(public_root.glob(f"r{index:02d}-*-fault"))
        control_dirs = sorted(public_root.glob(f"r{index:02d}-*-normal-control"))
        if len(fault_dirs) != 1 or len(control_dirs) != 1:
            raise ValueError(f"missing matched repetition {index}")
        fault = json.loads((fault_dirs[0] / "analysis.json").read_text())
        control = json.loads((control_dirs[0] / "analysis.json").read_text())
        latency = _paired_latency(fault, control)
        arm_order = (
            ["normal-control", "fault"]
            if index % 2 == 0
            else ["fault", "normal-control"]
        )
        result = {
            **fault,
            "arm_order": arm_order,
            "normal_control": control,
            "paired_latency": latency,
            "evidence_valid": (
                fault.get("evidence_valid") is True
                and control.get("evidence_valid") is True
                and latency.get("evaluable") is True
            ),
            "latency_pathology_evaluable": latency.get("evaluable") is True,
            "latency_pathology_observed": latency.get("observed"),
            "latency_pathology_reason": latency.get("reason"),
            "latency_top1_boundary": latency.get("top1_boundary"),
        }
        results.append(result)

    evidence_valid = all(result.get("evidence_valid", False) for result in results)
    correctness = all(result["correctness"] for result in results)
    resource_count = sum(bool(result["pathology_observed"]) for result in results)
    latency_evaluable = all(
        result.get("latency_pathology_evaluable", False) for result in results
    )
    latency_count = (
        sum(bool(result["latency_pathology_observed"]) for result in results)
        if latency_evaluable
        else None
    )
    boundary_counts: dict[str, int] = {}
    if latency_evaluable:
        for result in results:
            if result.get("latency_pathology_observed"):
                boundary = result.get("latency_top1_boundary")
                if isinstance(boundary, str):
                    boundary_counts[boundary] = boundary_counts.get(boundary, 0) + 1
    dominant = (
        max(boundary_counts, key=boundary_counts.get) if boundary_counts else None
    )
    dominant_count = boundary_counts[dominant] if dominant is not None else 0
    p99_values = [
        result["distribution"]["unaffected_survivor_p99_seconds"]
        for result in results
        if result["distribution"]["unaffected_survivor_p99_seconds"] is not None
    ]
    valid = evidence_valid and latency_evaluable
    go = valid and (resource_count >= 8 or dominant_count >= 8)
    return {
        "schema_version": "issue19-m0-baseline-summary/v2",
        "public_evidence_schema": PUBLIC_SCHEMA,
        "evidence_class": "real-online",
        "metadata": {"data_source": "real-online-oasst1-fixed-projection"},
        "completed_repetitions": len(results),
        "evidence_valid_100_percent": valid,
        "correctness_100_percent": correctness,
        "correctness_semantics": {
            "expected_fault_noncompletion": "not an evidence failure",
            "observed_false_reason": (
                "one evidence-valid repetition had a state-conservation failure"
            ),
            "universal_correctness_claim": False,
        },
        "resource_pathology_repetition_count": resource_count,
        "latency_pathology_evaluable": latency_evaluable,
        "latency_pathology_repetition_count": latency_count,
        "latency_top1_boundary_counts": boundary_counts,
        "dominant_latency_top1_boundary": dominant,
        "dominant_latency_top1_boundary_count": dominant_count,
        "pathology_repetition_count": max(resource_count, dominant_count),
        "required_pathology_repetition_count": 8,
        "go_for_treatment": go,
        "decision": "GO" if go else "NO_GO" if valid else "INVALID_EVIDENCE",
        "unaffected_survivor_p99_seconds": {
            "all": p99_values,
            "median": statistics.median(p99_values),
            "iqr": (
                statistics.quantiles(p99_values, n=4)[2]
                - statistics.quantiles(p99_values, n=4)[0]
            ),
        },
        "repetitions": results,
    }


def _public_leaks(root: Path, redactor: Redactor | None = None) -> list[str]:
    leaks: list[str] = []
    forbidden = (
        ("absolute_host_path", re.compile(r"/(?:root|home|tmp|dev)/")),
        ("private_address", PRIVATE_IPV4_RE),
        ("pci_address", PCI_RE),
        ("raw_npu_label", re.compile(r"(?i)\b(?:npu|device)[ _:=#-]*\d+\b")),
        ("raw_port", re.compile(r"(?<!\d)18179(?!\d)")),
    )
    raw_pids = tuple(redactor.pids) if redactor is not None else ()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        for name, pattern in forbidden:
            if pattern.search(relative) or pattern.search(text):
                leaks.append(f"{relative}: {name}")
        for pid in raw_pids:
            if re.search(rf"(?<!\d){re.escape(pid)}(?!\d)", relative + "\n" + text):
                leaks.append(f"{relative}: raw_pid")
                break
    return leaks


def export_public_artifacts(
    source_root: Path,
    public_root: Path,
    *,
    custody_manifest: Path | None = None,
) -> dict[str, Any]:
    if public_root.exists():
        raise FileExistsError(public_root)
    redactor = Redactor.from_source(source_root)
    public_root.mkdir(parents=True)
    entries: list[dict[str, Any]] = []

    for source in sorted(source_root.rglob("*")):
        if not source.is_file():
            continue
        relative = source.relative_to(source_root)
        safe_relative = redactor.relative_path(relative)
        base_entry = {
            "logical_path": safe_relative.as_posix(),
            "source_size": source.stat().st_size,
            "source_sha256": _sha256(source),
        }
        if source.name in WITHHELD_NAMES:
            entries.append({**base_entry, "action": "withheld-in-local-custody"})
            continue
        if source.name in DERIVED_NAMES:
            entries.append({**base_entry, "action": "recomputed-from-public-inputs"})
            continue
        destination = public_root / safe_relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix == ".json":
            _write_json(destination, redactor.value(json.loads(source.read_text())))
        elif source.suffix == ".jsonl":
            with destination.open("w", encoding="utf-8") as output:
                for document in _read_structured(source):
                    output.write(
                        json.dumps(redactor.value(document), sort_keys=True) + "\n"
                    )
        else:
            destination.write_text(
                redactor.text(source.read_text(encoding="utf-8")), encoding="utf-8"
            )
        entries.append(
            {
                **base_entry,
                "action": "sanitized-public-export",
                "public_size": destination.stat().st_size,
                "public_sha256": _sha256(destination),
            }
        )

    summary = recompute_summary(public_root)
    summary_path = public_root / "summary.json"
    _write_json(summary_path, summary)
    for entry in entries:
        if entry["logical_path"] == "summary.json":
            entry.update(
                {
                    "public_size": summary_path.stat().st_size,
                    "public_sha256": _sha256(summary_path),
                }
            )

    public_files = [
        path
        for path in sorted(public_root.rglob("*"))
        if path.is_file() and path.name != "redaction_manifest.json"
    ]
    manifest = {
        "schema_version": PUBLIC_SCHEMA,
        "sanitizer_version": SANITIZER_VERSION,
        "command": (
            "python -m vllm_request_lifecycle_profiler.issue19_public_artifacts "
            "export --source $RAW_CUSTODY --output $PUBLIC_EXPORT "
            "--custody-manifest $LOCAL_CUSTODY_MANIFEST"
        ),
        "policy": {
            "withheld": sorted(WITHHELD_NAMES),
            "redacted": [
                "absolute host paths",
                "loopback/private addresses and service port",
                "NPU device identifiers",
                "process identifiers",
                "PCI identifiers",
            ],
            "preserved": [
                "fault/control pairing",
                "request and resource identities",
                "mechanism events and ordering",
                "monotonic timestamps and numeric measurements",
                "experiment decision and complete repetition distribution",
            ],
        },
        "source_file_count": len(entries),
        "public_file_count_excluding_manifest": len(public_files),
        "summary_recomputed_from": [
            f"r{index:02d}-*/analysis.json" for index in range(10)
        ],
        "files": entries,
    }
    _write_json(public_root / "redaction_manifest.json", manifest)
    if custody_manifest is not None:
        _write_json(
            custody_manifest,
            {
                "schema_version": "issue19-local-custody/v1",
                "sanitizer_version": SANITIZER_VERSION,
                "source_file_count": len(entries),
                "files": [
                    {
                        "logical_path": entry["logical_path"],
                        "size": entry["source_size"],
                        "sha256": entry["source_sha256"],
                    }
                    for entry in entries
                ],
            },
        )
    leaks = _public_leaks(public_root, redactor)
    if leaks:
        raise ValueError("public export still contains topology: " + "; ".join(leaks))
    return manifest


def verify_public_artifacts(public_root: Path) -> dict[str, Any]:
    manifest_path = public_root / "redaction_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("sanitizer_version") != SANITIZER_VERSION:
        raise ValueError("sanitizer version mismatch")
    expected_hashes = {
        entry["logical_path"]: entry["public_sha256"]
        for entry in manifest["files"]
        if entry.get("public_sha256")
    }
    actual_files = {
        path.relative_to(public_root).as_posix()
        for path in public_root.rglob("*")
        if path.is_file() and path.name != "redaction_manifest.json"
    }
    if actual_files != set(expected_hashes):
        missing = sorted(set(expected_hashes) - actual_files)
        unlisted = sorted(actual_files - set(expected_hashes))
        raise ValueError(
            f"public file set mismatch: missing={missing}, unlisted={unlisted}"
        )
    declared_count = manifest.get("public_file_count_excluding_manifest")
    if declared_count != len(actual_files):
        raise ValueError(
            "public file count mismatch: "
            f"manifest={declared_count}, actual={len(actual_files)}"
        )
    withheld_names = set(manifest.get("policy", {}).get("withheld", []))
    leaked_withheld = sorted(
        relative for relative in actual_files if Path(relative).name in withheld_names
    )
    if leaked_withheld:
        raise ValueError(f"withheld files present in public export: {leaked_withheld}")
    for relative, expected in expected_hashes.items():
        path = public_root / relative
        if not path.is_file() or _sha256(path) != expected:
            raise ValueError(f"public file hash mismatch: {relative}")
    summary = recompute_summary(public_root)
    checked_in = json.loads((public_root / "summary.json").read_text())
    if summary != checked_in:
        raise ValueError("summary is not reproducible from sanitized analyses")
    leaks = _public_leaks(public_root)
    if leaks:
        raise ValueError("public export contains topology: " + "; ".join(leaks))
    return {
        "decision": summary["decision"],
        "evidence_valid_100_percent": summary["evidence_valid_100_percent"],
        "correctness_100_percent": summary["correctness_100_percent"],
        "resource_pathology_repetition_count": summary[
            "resource_pathology_repetition_count"
        ],
        "latency_pathology_repetition_count": summary[
            "latency_pathology_repetition_count"
        ],
        "verified_public_file_count": len(expected_hashes),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="action", required=True)
    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("--source", type=Path, required=True)
    export_parser.add_argument("--output", type=Path, required=True)
    export_parser.add_argument("--custody-manifest", type=Path)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--public-root", type=Path, required=True)
    args = parser.parse_args()
    result = (
        export_public_artifacts(
            args.source, args.output, custody_manifest=args.custody_manifest
        )
        if args.action == "export"
        else verify_public_artifacts(args.public_root)
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
