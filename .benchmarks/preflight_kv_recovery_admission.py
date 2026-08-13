"""G2 read-only NPU admission (version-aware whole-trace preflight).

Performs only read-only checks; it never starts a service or collects
performance data. On success it writes READY.txt (and removes BLOCKED.txt);
on any failure it writes BLOCKED.txt (and removes READY.txt). READY.txt must
exist only when BLOCKED.txt is absent.

Checks:
- device-owner: the selected NPU has no vllm-serving process and its HBM is
  near the idle baseline;
- model: the model path exists;
- schema/profile: current code profile/schema IDs match the sealed G1 shards
  (rlp.trace/v1alpha1, rlp.kv-recovery/v1alpha1,
  issue2:kv-recovery-v1alpha1);
- expected-process receipt: the G1 artifacts contain process_summary and
  profile_summary receipts, proving the committed-receipt mechanism works;
- trace-export: VLLM_RLP_TRACE_EXPORT_PATH is configured and writable;
- environment: VLLM_PLUGINS whitelist and xxhash availability.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
G1_RESULT_DIR = (
    REPO_ROOT / ".benchmarks" / "results" / "g1_cpu_controlled_trace_20260808"
)
RESULT_DIR = REPO_ROOT / ".benchmarks" / "results" / "g2_readonly_admission_20260808"

REQUIRED_PROFILES = {
    "base_schema": "rlp.trace/v1alpha1",
    "recovery_profile_id": "rlp.kv-recovery/v1alpha1",
    "communication_mode": "issue2:kv-recovery-v1alpha1",
}

# Default expected-process roster for the single-device in-process worker
# layout used by this project (APIServer parent + EngineCore child, worker
# in-process). G3 verifies one committed receipt per live roster member.
EXPECTED_PROCESS_ROSTER = ["api_server", "engine_core"]

IDLE_HBM_MARGIN_GB = 8.0  # > this much used HBM on the target NPU => assumed owned


def _git_head(path: Path) -> dict[str, str]:
    return {
        "commit": subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"], text=True
        ).strip(),
        "branch": subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "--abbrev-ref", "HEAD"], text=True
        ).strip(),
        "dirty_files": subprocess.check_output(
            ["git", "-C", str(path), "status", "--porcelain"], text=True
        ).count("\n"),
    }


def _npu_hbm_used_gb(device: int) -> float | None:
    try:
        out = subprocess.run(
            ["npu-smi", "info"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        ).stdout
    except Exception:  # noqa: BLE001 - preflight is fail-open.
        return None
    # Find the device header then its HBM row (next "| x | ... / 65536" line).
    lines = out.splitlines()
    for i, line in enumerate(lines):
        if re.match(rf"\|\s*{device}\s+910B2", line):
            for j in range(i + 1, min(i + 4, len(lines))):
                m = re.search(r"(\d+)\s*/\s*65536", lines[j])
                if m:
                    return int(m.group(1)) / 1024.0
            return None
    return None


def _has_vllm_process() -> bool:
    try:
        out = subprocess.run(
            ["ps", "-eo", "args"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        ).stdout
    except Exception:  # noqa: BLE001 - fail closed if we cannot inspect
        return True
    return any(
        "vllm serve" in line or "vllm.entrypoints" in line for line in out.splitlines()
    )


def _check_device_owner(device: int) -> dict[str, object]:
    used = _npu_hbm_used_gb(device)
    vllm_running = _has_vllm_process()
    ok = (used is not None and used <= IDLE_HBM_MARGIN_GB) and not vllm_running
    return {
        "ok": ok,
        "device": device,
        "hbm_used_gb": used,
        "vllm_process_running": vllm_running,
        "reason": None
        if ok
        else ("hbm_used" if used and used > IDLE_HBM_MARGIN_GB else "vllm_process"),
    }


def _check_model(model_path: str | None) -> dict[str, object]:
    if not model_path:
        return {"ok": False, "reason": "model_path_not_configured"}
    exists = Path(model_path).exists()
    return {
        "ok": exists,
        "path": model_path,
        "reason": None if exists else "model_path_not_found",
    }


def _load_profile_ids() -> dict[str, str] | None:
    try:
        from vllm_request_lifecycle_profiler.kv_recovery_profile_protocol import (
            PROFILE_ID,
        )
        from vllm_request_lifecycle_profiler.runtime_protocol import (
            KV_RECOVERY_COMMUNICATION_MODE,
            SCHEMA_VERSION,
        )
    except Exception:  # noqa: BLE001 - preflight is fail-open.
        return None
    return {
        "base_schema": SCHEMA_VERSION,
        "recovery_profile_id": PROFILE_ID,
        "communication_mode": KV_RECOVERY_COMMUNICATION_MODE,
    }


def _read_shard_records(shard: Path) -> list[dict[str, object]]:
    records = []
    for line in shard.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped:
            records.append(json.loads(stripped))
    return records


def _check_schema_profile() -> dict[str, object]:
    actual = _load_profile_ids()
    if actual is None:
        return {"ok": False, "reason": "plugin_import_failed", "actual": None}
    code_ok = actual == REQUIRED_PROFILES
    # Cross-check against the sealed G1 recovery shard header.
    shard = next(
        G1_RESULT_DIR.glob("recovery_episode/trace.rlp-kv-recovery.*.jsonl"), None
    )
    shard_ok = False
    shard_ids = None
    if shard is not None:
        rows = _read_shard_records(shard)
        start = next((r for r in rows if r.get("record_type") == "profile_start"), None)
        if start is not None:
            shard_ids = {
                "base_schema": start.get("base_trace_schema"),
                "recovery_profile_id": start.get("profile_id"),
                "communication_mode": start.get("communication_mode"),
            }
            shard_ok = shard_ids == REQUIRED_PROFILES
    return {
        "ok": code_ok and shard_ok,
        "code_ids": actual,
        "sealed_shard_ids": shard_ids,
        "shard": str(shard) if shard else None,
        "reason": None if (code_ok and shard_ok) else "profile_mismatch",
    }


def _check_expected_process_receipt() -> dict[str, object]:
    """Prove the committed-receipt mechanism using the sealed G1 shards."""
    base = next(G1_RESULT_DIR.glob("recovery_episode/trace.rlp.*.jsonl"), None)
    profile = next(
        G1_RESULT_DIR.glob("recovery_episode/trace.rlp-kv-recovery.*.jsonl"), None
    )
    if base is None or profile is None:
        return {"ok": False, "reason": "g1_shard_missing"}
    base_records = _read_shard_records(base)
    profile_records = _read_shard_records(profile)
    base_summary = any(r.get("record_type") == "process_summary" for r in base_records)
    profile_summary = any(
        r.get("record_type") == "profile_summary" for r in profile_records
    )
    ok = base_summary and profile_summary
    return {
        "ok": ok,
        "expected_roster": EXPECTED_PROCESS_ROSTER,
        "base_process_summary_present": base_summary,
        "recovery_profile_summary_present": profile_summary,
        "reason": None if ok else "missing_receipt",
    }


def _check_trace_export() -> dict[str, object]:
    value = os.environ.get("VLLM_RLP_TRACE_EXPORT_PATH", "").strip()
    if not value:
        return {
            "ok": False,
            "reason": "VLLM_RLP_TRACE_EXPORT_PATH_not_set",
            "path": None,
        }
    path = Path(value).expanduser()
    parent = path.parent
    parent_ok = parent.exists() and parent.is_dir()
    writable = parent_ok and os.access(parent, os.W_OK)
    return {
        "ok": writable,
        "path": str(path),
        "parent_writable": writable,
        "reason": None if writable else "trace_export_parent_not_writable",
    }


def _check_endpoint() -> dict[str, object]:
    """Check a running service's /v1/models endpoint when one exists.

    G2 is read-only and must not start a service, so when no endpoint is
    reachable this check is recorded as deferred to G3 (the minimum online
    trace smoke) rather than failing the environment/contract admission.
    """
    import urllib.error
    import urllib.request

    endpoint = os.environ.get("VLLM_RLP_ENDPOINT", "").strip()
    if not endpoint:
        return {
            "ok": True,
            "deferred_to_g3": True,
            "reason": "no_endpoint_configured_readonly_g2",
            "endpoint": None,
        }
    url = endpoint.rstrip("/") + "/v1/models"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            body = json.loads(response.read().decode("utf-8"))
            ok = response.status == 200 and isinstance(body.get("data"), list)
            return {
                "ok": ok,
                "deferred_to_g3": False,
                "endpoint": endpoint,
                "model_count": len(body.get("data", [])),
                "reason": None if ok else "models_endpoint_invalid",
            }
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        OSError,
    ) as exc:
        return {
            "ok": True,
            "deferred_to_g3": True,
            "reason": f"endpoint_unreachable_readonly_g2:{type(exc).__name__}",
            "endpoint": endpoint,
        }


def _check_environment() -> dict[str, object]:
    plugins = os.environ.get("VLLM_PLUGINS", "").strip()
    plugins_ok = {p.strip() for p in plugins.split(",") if p.strip()} >= {
        "ascend",
        "request_lifecycle_profiler",
    }
    try:
        import xxhash  # noqa: F401

        xxhash_ok = True
    except Exception:  # noqa: BLE001 - preflight is fail-open.
        xxhash_ok = False
    return {
        "ok": plugins_ok and xxhash_ok,
        "vllm_plugins": plugins,
        "xxhash_available": xxhash_ok,
        "reason": None
        if (plugins_ok and xxhash_ok)
        else ("plugins" if not plugins_ok else "xxhash"),
    }


def _clean_markers() -> None:
    (RESULT_DIR / "READY.txt").unlink(missing_ok=True)
    (RESULT_DIR / "BLOCKED.txt").unlink(missing_ok=True)


def main() -> int:
    device = int(os.environ.get("ASCEND_RT_VISIBLE_DEVICES", "6").split(",")[0].strip())
    model_path = os.environ.get(
        "VLLM_RLP_MODEL_PATH", "/data/shared_datasets/Qwen--Qwen2.5-Coder-14B-Instruct"
    )

    checks = {
        "endpoint": _check_endpoint(),
        "device_owner": _check_device_owner(device),
        "model": _check_model(model_path),
        "schema_profile": _check_schema_profile(),
        "expected_process_receipt": _check_expected_process_receipt(),
        "trace_export": _check_trace_export(),
        "environment": _check_environment(),
    }
    blockers = [name for name, result in checks.items() if not result["ok"]]
    deferred = [name for name, result in checks.items() if result.get("deferred_to_g3")]

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    if RESULT_DIR.exists():
        # If both markers exist, the previous state is ambiguous: fail closed
        # by archiving the old directory and re-evaluating fresh.
        both = (RESULT_DIR / "READY.txt").exists() and (
            RESULT_DIR / "BLOCKED.txt"
        ).exists()
        if both:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            RESULT_DIR.rename(
                RESULT_DIR.with_name(RESULT_DIR.name + f".ambiguous_{stamp}")
            )
            RESULT_DIR.mkdir(parents=True)

    _clean_markers()
    if blockers:
        (RESULT_DIR / "BLOCKED.txt").write_text(
            "BLOCKED: version-aware whole-trace preflight did not pass.\n"
            + "".join(f"- {name}: {checks[name].get('reason')}\n" for name in blockers)
            + "This is readiness evidence only, not a paper measurement.\n",
            encoding="utf-8",
        )
    else:
        (RESULT_DIR / "READY.txt").write_text(
            "READY: read-only version-aware preflight passed. Run the G3 "
            "minimum online trace smoke next.\nThis is readiness evidence "
            "only, not a paper measurement.\n",
            encoding="utf-8",
        )

    run_metadata = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": " ".join(sys.argv),
        "python": sys.version.split()[0],
        "selected_device": device,
        "expected_process_roster": EXPECTED_PROCESS_ROSTER,
        "profiler_repo": {"path": str(REPO_ROOT), **_git_head(REPO_ROOT)},
        "runtime_repo": {
            "path": "/root/vllm-hust-g1-default-off-f229ba7",
            **_git_head(Path("/root/vllm-hust-g1-default-off-f229ba7")),
        },
        "checks": checks,
        "blockers": blockers,
        "deferred_to_g3": deferred,
    }
    (RESULT_DIR / "run_metadata.json").write_text(
        json.dumps(run_metadata, indent=2) + "\n", encoding="utf-8"
    )

    print(
        json.dumps(
            {
                k: {
                    "ok": v["ok"],
                    "reason": v.get("reason"),
                    "deferred_to_g3": v.get("deferred_to_g3", False),
                }
                for k, v in checks.items()
            },
            indent=2,
        )
    )
    print("G2_READONLY_ADMISSION:", "PASS" if not blockers else "BLOCKED")
    print("deferred_to_g3:", deferred)
    return 0 if not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
