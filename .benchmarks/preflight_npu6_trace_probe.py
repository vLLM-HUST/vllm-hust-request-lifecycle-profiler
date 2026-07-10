from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.parse import urljoin
from urllib.request import Request
from urllib.request import urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKLOAD_SUBMODULE = REPO_ROOT / "third_party" / "llm-serving-workloads"
REQUIRED_TRACE_FIELDS = {
    "request_id",
    "stage",
    "timestamp_ms",
}
OPTIONAL_TRACE_FIELDS = {
    "metadata",
    "sequence_id",
    "engine_request_id",
    "trace_id",
}


def _git(args: list[str], *, cwd: Path = REPO_ROOT) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=False)


def _git_metadata() -> dict[str, Any]:
    workload: dict[str, Any] = {
        "path": str(WORKLOAD_SUBMODULE),
        "exists": WORKLOAD_SUBMODULE.is_dir(),
    }
    if WORKLOAD_SUBMODULE.is_dir():
        workload.update(
            {
                "commit": _git(["rev-parse", "HEAD"], cwd=WORKLOAD_SUBMODULE),
                "branch": _git(["branch", "--show-current"], cwd=WORKLOAD_SUBMODULE),
                "dirty": bool(_git(["status", "--short"], cwd=WORKLOAD_SUBMODULE)),
            }
        )
    return {
        "parent_commit": _git(["rev-parse", "HEAD"]),
        "parent_branch": _git(["branch", "--show-current"]),
        "parent_dirty": bool(_git(["status", "--short"])),
        "workload_source": workload,
    }


def _discover_ascend_runtime_root(configured: str | None) -> dict[str, Any]:
    candidates: list[str] = []
    if configured:
        candidates.append(configured)
    for name in ("ASCEND_HOME_PATH", "ASCEND_TOOLKIT_HOME", "ASCEND_ROOT"):
        value = os.environ.get(name)
        if value:
            candidates.append(value)
    candidates.extend(
        [
            "/usr/local/Ascend/ascend-toolkit/latest",
            "/usr/local/Ascend/ascend-toolkit",
            "/usr/local/Ascend/latest",
            "/usr/local/Ascend/cann-8.5.1",
            "/usr/local/Ascend",
        ]
    )

    checked = []
    for candidate in dict.fromkeys(candidates):
        path = Path(candidate).expanduser()
        checked.append(str(path))
        if path.exists():
            return {"ok": True, "path": str(path), "checked": checked}
    return {"ok": False, "path": None, "checked": checked}


def _request_json(endpoint: str, token_env: str, timeout_s: float) -> dict[str, Any]:
    token = os.environ.get(token_env)
    request = Request(urljoin(endpoint.rstrip("/") + "/", "v1/models"))
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urlopen(request, timeout=timeout_s) as response:
            body = response.read().decode("utf-8")
            return {
                "ok": True,
                "status": response.status,
                "token_env_present": bool(token),
                "json": json.loads(body),
            }
    except HTTPError as exc:
        return {
            "ok": False,
            "status": exc.code,
            "token_env_present": bool(token),
            "error": f"http_error:{exc.code}",
        }
    except (TimeoutError, URLError) as exc:
        return {
            "ok": False,
            "status": None,
            "token_env_present": bool(token),
            "error": f"connection_error:{exc}",
        }
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "status": None,
            "token_env_present": bool(token),
            "error": f"invalid_json:{exc}",
        }


def _trace_records(path: Path, limit: int = 128) -> list[dict[str, Any]]:
    if path.suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return [record for record in payload[:limit] if isinstance(record, dict)]
        if isinstance(payload, dict) and isinstance(payload.get("events"), list):
            return [record for record in payload["events"][:limit] if isinstance(record, dict)]
        if isinstance(payload, dict):
            return [payload]
        return []

    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if len(records) >= limit:
                break
            stripped = line.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            if isinstance(payload, dict):
                records.append(payload)
    return records


def _validate_trace_export(path_value: str | None) -> dict[str, Any]:
    if not path_value:
        return {
            "ok": False,
            "path": None,
            "error": "missing_trace_export_path",
            "required_fields": sorted(REQUIRED_TRACE_FIELDS),
            "optional_fields": sorted(OPTIONAL_TRACE_FIELDS),
        }

    path = Path(path_value).expanduser()
    if not path.exists():
        return {
            "ok": False,
            "path": str(path),
            "error": "trace_export_path_not_found",
            "parent_exists": path.parent.exists(),
            "required_fields": sorted(REQUIRED_TRACE_FIELDS),
            "optional_fields": sorted(OPTIONAL_TRACE_FIELDS),
        }
    if path.is_dir():
        candidates = sorted(path.glob("*.jsonl")) + sorted(path.glob("*.json"))
        if not candidates:
            return {
                "ok": False,
                "path": str(path),
                "error": "trace_export_dir_has_no_json_or_jsonl",
                "required_fields": sorted(REQUIRED_TRACE_FIELDS),
                "optional_fields": sorted(OPTIONAL_TRACE_FIELDS),
            }
        path = candidates[0]

    try:
        records = _trace_records(path)
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "path": str(path),
            "error": f"trace_export_parse_error:{exc}",
            "required_fields": sorted(REQUIRED_TRACE_FIELDS),
            "optional_fields": sorted(OPTIONAL_TRACE_FIELDS),
        }

    missing_rows = [
        {
            "index": index,
            "missing": sorted(REQUIRED_TRACE_FIELDS - set(record)),
        }
        for index, record in enumerate(records)
        if REQUIRED_TRACE_FIELDS - set(record)
    ]
    return {
        "ok": bool(records) and not missing_rows,
        "path": str(path),
        "record_count_checked": len(records),
        "missing_rows": missing_rows[:8],
        "required_fields": sorted(REQUIRED_TRACE_FIELDS),
        "optional_fields": sorted(OPTIONAL_TRACE_FIELDS),
        "timestamp_unit": "milliseconds",
    }


def _npu_processes(npu_smi_output: str, npu_id: int) -> list[dict[str, str]]:
    processes: list[dict[str, str]] = []
    for line in npu_smi_output.splitlines():
        stripped = line.strip("| ")
        if "No running processes found in NPU" in stripped:
            continue
        columns = [part.strip() for part in line.strip().strip("|").split("|")]
        if len(columns) < 4:
            continue
        npu_chip = columns[0].split()
        if len(npu_chip) < 2:
            continue
        npu, chip = npu_chip[:2]
        pid, process_name, process_memory = columns[1:4]
        if npu.isdigit() and pid.isdigit() and npu == str(npu_id):
            processes.append(
                {
                    "npu": npu,
                    "chip": chip,
                    "pid": pid,
                    "process_name": process_name,
                    "process_memory_mb": process_memory.split()[0],
                }
            )
    return processes


def _npu_status(npu_id: int) -> dict[str, Any]:
    result = _run(["npu-smi", "info"])
    if result.returncode != 0:
        return {
            "ok": False,
            "error": "npu_smi_failed",
            "returncode": result.returncode,
            "stderr": result.stderr[-2000:],
            "processes": [],
        }
    processes = _npu_processes(result.stdout, npu_id)
    return {
        "ok": True,
        "error": None,
        "processes": processes,
        "has_process_on_requested_npu": bool(processes),
    }


def _metadata(args: argparse.Namespace) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "evidence_label": "existing-server-probe",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "command": " ".join(sys.argv),
        "output_dir": args.output_dir,
        "npu_id": args.npu_id,
        "endpoint": args.endpoint,
        "api_token_env": args.api_token_env,
        "api_token_value_recorded": False,
        "model_path": args.model_path,
        "trace_export_path": args.trace_export_path,
        "conda_env": os.environ.get("CONDA_DEFAULT_ENV", ""),
        "result_valid_for_paper_claims": False,
    }
    metadata.update(_git_metadata())
    metadata["ascend_runtime_root"] = _discover_ascend_runtime_root(args.ascend_runtime_root)
    metadata["model_path_exists"] = bool(args.model_path and Path(args.model_path).exists())
    metadata["models_endpoint"] = _request_json(
        args.endpoint,
        args.api_token_env,
        args.timeout_s,
    )
    metadata["trace_export"] = _validate_trace_export(args.trace_export_path)
    metadata["npu_smi"] = _npu_status(args.npu_id)
    return metadata


def _blockers(metadata: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if not metadata["ascend_runtime_root"]["ok"]:
        blockers.append("ascend_runtime_root_missing")
    if not metadata["model_path"]:
        blockers.append("model_path_missing")
    elif not metadata["model_path_exists"]:
        blockers.append("model_path_not_found")
    if not metadata["models_endpoint"]["ok"]:
        blockers.append("models_endpoint_failed")
    if not metadata["trace_export"]["ok"]:
        blockers.append(f"trace_export_invalid:{metadata['trace_export'].get('error', 'schema')}")
    npu_smi = metadata["npu_smi"]
    if not npu_smi["ok"]:
        blockers.append("npu_smi_failed")
    elif not npu_smi["has_process_on_requested_npu"]:
        blockers.append("no_process_on_npu6")
    return blockers


def _write_blocked(output_dir: Path, blockers: list[str], metadata: dict[str, Any]) -> None:
    lines = [
        "BLOCKED: NPU6 existing-server trace probe preflight did not pass.",
        "",
        "Blocking checks:",
    ]
    lines.extend(f"- {blocker}" for blocker in blockers)
    lines.extend(
        [
            "",
            "This directory is invalid for paper claims. It records readiness gaps only.",
            "API token values are intentionally not written to metadata.",
        ]
    )
    (output_dir / "BLOCKED.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    metadata["blockers"] = blockers
    metadata["preflight_passed"] = False
    metadata["result_valid_for_paper_claims"] = False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only NPU6 existing-server trace-probe preflight."
    )
    parser.add_argument("--endpoint", default=os.environ.get("VLLM_RLP_ENDPOINT", "http://127.0.0.1:18080"))
    parser.add_argument("--model-path", default=os.environ.get("VLLM_RLP_MODEL_PATH", ""))
    parser.add_argument("--trace-export-path", default=os.environ.get("VLLM_RLP_TRACE_EXPORT_PATH", ""))
    parser.add_argument("--api-token-env", default=os.environ.get("VLLM_RLP_API_TOKEN_ENV", "VLLM_RLP_API_TOKEN"))
    parser.add_argument("--ascend-runtime-root", default=os.environ.get("VLLM_RLP_ASCEND_RUNTIME_ROOT", ""))
    parser.add_argument("--npu-id", type=int, default=6)
    parser.add_argument("--timeout-s", type=float, default=5.0)
    parser.add_argument(
        "--output-dir",
        default=".benchmarks/results/npu6_trace_probe_preflight",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata = _metadata(args)
    blockers = _blockers(metadata)
    if blockers:
        _write_blocked(output_dir, blockers, metadata)
    else:
        metadata["preflight_passed"] = True
        metadata["result_valid_for_paper_claims"] = False
        stale_blocked = output_dir / "BLOCKED.txt"
        if stale_blocked.exists():
            stale_blocked.unlink()
        (output_dir / "READY.txt").write_text(
            "READY: read-only preflight passed. Run the actual trace probe workload next.\n"
            "This directory is readiness evidence only, not a paper measurement.\n",
            encoding="utf-8",
        )

    (output_dir / "run_metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                "blocked": bool(blockers),
                "blockers": blockers,
                "result_valid_for_paper_claims": metadata["result_valid_for_paper_claims"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
