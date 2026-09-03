"""Fail-closed readiness and fixed execution plan for Issue #19 M0.

This module prepares an observer-only experiment.  It deliberately does not
start vLLM, inject failures, enable a reconciliation treatment, or label its
outputs as real-online evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from vllm_request_lifecycle_profiler.oasst1_workload import (
    DEFAULT_DATA_CACHE,
    DEFAULT_MAX_MODEL_LEN,
    OASST1_FILENAME,
    OASST1_REVISION,
    build_oasst1_repetitions,
    build_projection_manifest,
    preflight_context_lengths,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = REPO_ROOT / ".benchmarks" / "results" / "m0_issue19_preflight"
DEFAULT_RUNTIME = REPO_ROOT / "third_party" / "vllm-hust"
DEFAULT_ASCEND = REPO_ROOT / "third_party" / "vllm-ascend-hust"
DEFAULT_MODEL = (
    Path.home()
    / ".cache/huggingface/hub/models--Qwen--Qwen2.5-14B-Instruct"
    / "snapshots/cf98f3b3bbb457ad9e2bb7baf9a0125b6b88caa8"
)
SUPPORTED_RELEASE = "0.23.0"
TARGET_MODEL = "Qwen/Qwen2.5-14B-Instruct"
TARGET_DTYPE = "bfloat16"
TARGET_MAX_MODEL_LEN = DEFAULT_MAX_MODEL_LEN
TARGET_KV_CACHE_MEMORY_BYTES = 2 * 1024**3
TARGET_CPU_OFFLOAD_BYTES = 8 * 1024**3
TARGET_KV_BLOCK_SIZE = 128
TARGET_CONNECTOR = "OffloadingConnector"
TARGET_OFFLOADING_SPEC = "TieringOffloadingSpec"

SEEDS = tuple(range(2026082000, 2026082010))
SCENARIO_TARGET_ORDINALS = {
    "normal_completion": 0,
    "client_disconnect": 1,
    "client_timeout": 2,
    "duplicate_cancel": 3,
    "recovery": 4,
    "worker_exit": 5,
}
SCENARIO_ORDER = tuple(SCENARIO_TARGET_ORDINALS)


@dataclass(frozen=True)
class VersionMetadata:
    release_version: str
    upstream_version: str
    upstream_commit: str


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    observed: Any
    expected: Any
    blocker: str | None = None


def _git_head(repository: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _git_worktree_clean(repository: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repository), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    )
    return not result.stdout.strip()


def _load_version_metadata(repository: Path) -> VersionMetadata:
    values = json.loads((repository / "upstream_version.json").read_text())
    return VersionMetadata(
        release_version=values["release_version"],
        upstream_version=values["upstream_version"],
        upstream_commit=values["upstream_commit"],
    )


def _runtime_torch_requirement(repository: Path) -> str:
    text = (repository / "pyproject.toml").read_text()
    match = re.search(r'["\']torch\s*==\s*([^;\s"\']+)', text)
    if match:
        return match.group(1)
    raise ValueError("runtime build-system does not pin torch")


def _ascend_torch_requirement(repository: Path) -> str:
    for line in (repository / "requirements.txt").read_text().splitlines():
        match = re.fullmatch(r"torch\s*==\s*([^;\s]+)", line.strip())
        if match:
            return match.group(1)
    raise ValueError("Ascend requirements do not pin torch")


def _ascend_torch_npu_requirement(repository: Path) -> str:
    for line in (repository / "requirements.txt").read_text().splitlines():
        match = re.fullmatch(r"torch-npu\s*==\s*([^;\s]+)", line.strip())
        if match:
            return match.group(1)
    raise ValueError("Ascend requirements do not pin torch-npu")


def _ascend_documented_vllm_version(repository: Path) -> str:
    text = (repository / "docs/source/conf.py").read_text()
    match = re.search(r'"pip_vllm_version"\s*:\s*"([^"]+)"', text)
    if match:
        return match.group(1)
    raise ValueError("Ascend documentation does not declare pip_vllm_version")


def _base_version(version: str | None) -> str | None:
    return version.split("+", 1)[0] if version else None


def collect_python_environment(
    python: Path, runtime: Path, ascend: Path
) -> dict[str, Any]:
    """Inspect the serving interpreter without importing vLLM itself."""

    probe = """
import importlib.metadata
import importlib.util
import json
import platform
import sys

def origin(name):
    spec = importlib.util.find_spec(name)
    return None if spec is None else spec.origin

versions = {}
for name in ("vllm", "torch", "torch_npu", "transformers"):
    try:
        module = __import__(name)
        versions[name] = getattr(module, "__version__", None)
    except Exception as exc:
        versions[name] = {"error": f"{type(exc).__name__}: {exc}"}
distributions = {}
for name in ("vllm", "torch", "torch-npu", "transformers"):
    try:
        distributions[name] = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        distributions[name] = None
print(json.dumps({
    "executable": sys.executable,
    "python_version": platform.python_version(),
    "versions": versions,
    "distributions": distributions,
    "origins": {"vllm": origin("vllm"), "vllm_ascend": origin("vllm_ascend")},
}, sort_keys=True))
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(runtime), str(ascend)))
    result = subprocess.run(
        [str(python), "-c", probe],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    return json.loads(result.stdout)


def probe_source_compatibility(
    python: Path,
    runtime: Path,
    ascend: Path,
    release_version: str,
) -> dict[str, Any]:
    """Import the supported cross-repository seam under Ascend's version gate."""

    probe = f"""
import json
from vllm_ascend.utils import vllm_version_is
from vllm.v1.engine.request_lifecycle_hooks import (
    observe_request_started,
    observe_resource_transition,
)
from vllm_ascend.worker.kv_recovery import observe_first_compute_if_supported
print("ISSUE19_COMPAT=" + json.dumps({{
    "vllm_version_gate": vllm_version_is({release_version!r}),
    "runtime_lifecycle_seam": callable(observe_request_started),
    "runtime_resource_seam": callable(observe_resource_transition),
    "ascend_first_compute_seam": callable(observe_first_compute_if_supported),
}}, sort_keys=True))
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(runtime), str(ascend)))
    environment["VLLM_VERSION"] = release_version
    result = subprocess.run(
        [str(python), "-c", probe],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    marker = "ISSUE19_COMPAT="
    payload = next(
        (
            line.removeprefix(marker)
            for line in reversed(result.stdout.splitlines())
            if line.startswith(marker)
        ),
        None,
    )
    details = json.loads(payload) if payload is not None else {}
    return {
        "passed": result.returncode == 0 and bool(details) and all(details.values()),
        "returncode": result.returncode,
        "details": details,
        "stderr_tail": result.stderr.splitlines()[-5:],
    }


def probe_ascend_kv_cache_compatibility(
    python: Path,
    runtime: Path,
    ascend: Path,
    release_version: str,
) -> dict[str, Any]:
    """Exercise the runtime connector with Ascend's tuple-shaped attention KV."""

    probe = """
import json
from types import SimpleNamespace

import torch
from vllm.distributed.kv_transfer.kv_connector.v1.offloading.worker import (
    OffloadingConnectorWorker,
)
from vllm.v1.kv_cache_interface import (
    FullAttentionSpec,
    KVCacheConfig,
    KVCacheGroupSpec,
    KVCacheTensor,
)

layer_name = "model.layers.0.self_attn.attn"
attention_spec = FullAttentionSpec(
    block_size=1,
    num_kv_heads=1,
    head_size=1,
    dtype=torch.float32,
)
config = KVCacheConfig(
    num_blocks=1,
    kv_cache_tensors=[KVCacheTensor(size=8, shared_by=[layer_name])],
    kv_cache_groups=[KVCacheGroupSpec([layer_name], attention_spec)],
)
worker = OffloadingConnectorWorker.__new__(OffloadingConnectorWorker)
worker.spec = SimpleNamespace(
    kv_cache_config=config,
    get_handlers=lambda _canonical: (),
)
captured = []
worker._register_handlers = captured.append
details = {
    "input_representation": "tuple[k_cache, v_cache]",
    "runtime_connector": "OffloadingConnectorWorker.register_kv_caches",
}
try:
    worker.register_kv_caches(
        {
            layer_name: (
                torch.zeros((1, 1, 1, 1), dtype=torch.float32),
                torch.zeros((1, 1, 1, 1), dtype=torch.float32),
            )
        }
    )
    canonical = captured[0] if captured else None
    tensor_count = len(canonical.tensors) if canonical is not None else 0
    details.update({"accepted": True, "canonical_tensor_count": tensor_count})
    passed = tensor_count == 2
except Exception as exc:
    details.update({
        "accepted": False,
        "error": f"{type(exc).__name__}: {exc}",
    })
    passed = False
print("ISSUE19_ASCEND_KV=" + json.dumps({"passed": passed, "details": details}, sort_keys=True))
"""
    environment = os.environ.copy()
    existing_pythonpath = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(runtime), str(ascend), existing_pythonpath) if part
    )
    environment["VLLM_VERSION"] = release_version
    environment["VLLM_PLUGINS"] = "ascend"
    result = subprocess.run(
        [str(python), "-c", probe],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    marker = "ISSUE19_ASCEND_KV="
    payload = next(
        (
            line.removeprefix(marker)
            for line in reversed(result.stdout.splitlines())
            if line.startswith(marker)
        ),
        None,
    )
    parsed = json.loads(payload) if payload is not None else {}
    return {
        "passed": result.returncode == 0 and parsed.get("passed") is True,
        "returncode": result.returncode,
        "details": parsed.get("details", {}),
        "stderr_tail": result.stderr.splitlines()[-5:],
    }


def inspect_kv_capacity_gate(
    model_path: Path,
    *,
    max_model_len: int = TARGET_MAX_MODEL_LEN,
    kv_cache_memory_bytes: int = TARGET_KV_CACHE_MEMORY_BYTES,
    block_size: int = TARGET_KV_BLOCK_SIZE,
) -> dict[str, Any]:
    """Calculate whether the fixed KV capacity can admit one full request."""

    try:
        config = json.loads((model_path / "config.json").read_text())
        hidden_size = int(config["hidden_size"])
        attention_heads = int(config["num_attention_heads"])
        kv_heads = int(config["num_key_value_heads"])
        layers = int(config["num_hidden_layers"])
        head_dim = int(config.get("head_dim") or hidden_size // attention_heads)
        dtype = str(config.get("torch_dtype", TARGET_DTYPE)).removeprefix("torch.")
        element_sizes = {
            "bfloat16": 2,
            "float16": 2,
            "float32": 4,
        }
        element_size = element_sizes[dtype]
        bytes_per_token = 2 * layers * kv_heads * head_dim * element_size
        bytes_per_block = bytes_per_token * block_size
        capacity_blocks = kv_cache_memory_bytes // bytes_per_block
        capacity_tokens = capacity_blocks * block_size
        required_blocks = (max_model_len + block_size - 1) // block_size
        required_bytes = required_blocks * bytes_per_block
    except Exception as exc:  # noqa: BLE001 - converted into a fail-closed blocker.
        return {"passed": False, "error": f"{type(exc).__name__}: {exc}"}
    return {
        "passed": capacity_tokens >= max_model_len,
        "model_dtype": dtype,
        "bytes_per_token": bytes_per_token,
        "block_size": block_size,
        "kv_cache_memory_bytes": kv_cache_memory_bytes,
        "capacity_tokens": capacity_tokens,
        "max_model_len": max_model_len,
        "required_bytes": required_bytes,
    }


def _origin_is_within(origin: object, repository: Path) -> bool:
    if not isinstance(origin, str):
        return False
    try:
        Path(origin).resolve().relative_to(repository.resolve())
    except ValueError:
        return False
    return True


def inspect_serving_readiness(
    *,
    profiler: Path | None = None,
    runtime: Path = DEFAULT_RUNTIME,
    ascend: Path = DEFAULT_ASCEND,
    runtime_python: Path,
    model_path: Path = DEFAULT_MODEL,
) -> dict[str, Any]:
    runtime_version = _load_version_metadata(runtime)
    ascend_version = _load_version_metadata(ascend)
    runtime_torch = _runtime_torch_requirement(runtime)
    ascend_torch = _ascend_torch_requirement(ascend)
    ascend_torch_npu = _ascend_torch_npu_requirement(ascend)
    ascend_documented_vllm = _ascend_documented_vllm_version(ascend)
    python_environment = collect_python_environment(runtime_python, runtime, ascend)
    source_compatibility = probe_source_compatibility(
        runtime_python,
        runtime,
        ascend,
        runtime_version.release_version,
    )
    ascend_kv_cache_compatibility = probe_ascend_kv_cache_compatibility(
        runtime_python,
        runtime,
        ascend,
        runtime_version.release_version,
    )
    kv_capacity_gate = inspect_kv_capacity_gate(model_path)
    installed_torch = python_environment["versions"].get("torch")
    if not isinstance(installed_torch, str):
        installed_torch = None
    installed_vllm = python_environment["versions"].get("vllm")
    if not isinstance(installed_vllm, str):
        installed_vllm = None
    installed_torch_npu = python_environment.get("distributions", {}).get("torch-npu")
    profiler_clean = _git_worktree_clean(profiler) if profiler is not None else None
    runtime_clean = _git_worktree_clean(runtime)
    ascend_clean = _git_worktree_clean(ascend)
    ownership_sources = {
        "kv_capacity_lease": runtime / "vllm/v1/core/kv_cache_manager.py",
        "offload_transfer": (
            runtime
            / "vllm/distributed/kv_transfer/kv_connector/v1/offloading/worker.py"
        ),
        "fatal_invalidation": runtime / "vllm/v1/engine/core.py",
    }
    ownership_markers = {
        "kv_capacity_lease": "_observe_kv_lease_acquired",
        "offload_transfer": "_observe_transfer_resource",
        "fatal_invalidation": "invalidate_observed_resource_leases",
    }
    ownership_wiring = {
        name: path.is_file() and ownership_markers[name] in path.read_text()
        for name, path in ownership_sources.items()
    }

    checks = [
        *(
            [
                Check(
                    "profiler_worktree_clean",
                    profiler_clean is True,
                    profiler_clean,
                    True,
                    "profiler_worktree_has_uncommitted_changes",
                )
            ]
            if profiler is not None
            else []
        ),
        Check(
            "runtime_worktree_clean",
            runtime_clean,
            runtime_clean,
            True,
            "runtime_worktree_has_uncommitted_changes",
        ),
        Check(
            "ascend_worktree_clean",
            ascend_clean,
            ascend_clean,
            True,
            "ascend_worktree_has_uncommitted_changes",
        ),
        Check(
            "runtime_ascend_release_line",
            runtime_version.release_version
            == ascend_version.release_version
            == SUPPORTED_RELEASE,
            {
                "runtime": runtime_version.release_version,
                "ascend": ascend_version.release_version,
            },
            f"both repositories on supported {SUPPORTED_RELEASE}",
            "pinned_runtime_ascend_version_mismatch",
        ),
        Check(
            "ascend_documented_runtime",
            ascend_documented_vllm == runtime_version.release_version,
            ascend_documented_vllm,
            runtime_version.release_version,
            "ascend_documented_runtime_mismatch",
        ),
        Check(
            "ascend_owned_torch_stack",
            _base_version(installed_torch) == _base_version(ascend_torch),
            {
                "installed": installed_torch,
                "ascend_runtime": ascend_torch,
                "runtime_build_isolation": runtime_torch,
            },
            "installed Torch matches Ascend; vLLM uses the empty carrier",
            "installed_torch_does_not_match_ascend",
        ),
        Check(
            "installed_ascend_torch",
            _base_version(installed_torch) == _base_version(ascend_torch),
            installed_torch,
            ascend_torch,
            "installed_torch_does_not_match_ascend",
        ),
        Check(
            "installed_ascend_torch_npu",
            installed_torch_npu == ascend_torch_npu,
            installed_torch_npu,
            ascend_torch_npu,
            "installed_torch_npu_does_not_match_ascend",
        ),
        Check(
            "installed_empty_runtime_carrier",
            _base_version(installed_vllm) == runtime_version.release_version,
            installed_vllm,
            f"{runtime_version.release_version}+empty",
            "installed_vllm_carrier_version_mismatch",
        ),
        Check(
            "pinned_runtime_import_origin",
            _origin_is_within(python_environment["origins"].get("vllm"), runtime),
            python_environment["origins"].get("vllm"),
            str(runtime.resolve()),
            "runtime_import_is_not_pinned_submodule",
        ),
        Check(
            "pinned_ascend_import_origin",
            _origin_is_within(python_environment["origins"].get("vllm_ascend"), ascend),
            python_environment["origins"].get("vllm_ascend"),
            str(ascend.resolve()),
            "ascend_import_is_not_pinned_submodule",
        ),
        Check(
            "runtime_ascend_source_compatibility",
            source_compatibility["passed"],
            source_compatibility,
            "runtime lifecycle and Ascend first-compute seams import together",
            "runtime_ascend_source_import_failed",
        ),
        Check(
            "ascend_offloading_connector_kv_cache_compatibility",
            ascend_kv_cache_compatibility["passed"],
            ascend_kv_cache_compatibility,
            "runtime connector accepts Ascend tuple[k_cache, v_cache] entries",
            "ascend_offloading_connector_kv_cache_incompatible",
        ),
        Check(
            "target_kv_capacity",
            kv_capacity_gate["passed"],
            kv_capacity_gate,
            (
                f"{TARGET_KV_CACHE_MEMORY_BYTES} bytes admit "
                f"max_model_len={TARGET_MAX_MODEL_LEN}"
            ),
            "target_kv_capacity_cannot_admit_max_model_len",
        ),
        Check(
            "kv_recovery_runtime_observer",
            (runtime / "vllm/v1/kv_recovery_profile.py").is_file(),
            (runtime / "vllm/v1/kv_recovery_profile.py").is_file(),
            True,
            "kv_recovery_runtime_observer_missing",
        ),
        Check(
            "kv_recovery_ascend_first_compute",
            (ascend / "vllm_ascend/worker/kv_recovery.py").is_file(),
            (ascend / "vllm_ascend/worker/kv_recovery.py").is_file(),
            True,
            "kv_recovery_ascend_first_compute_missing",
        ),
        Check(
            "general_request_lifecycle_hook",
            (runtime / "vllm/v1/engine/request_lifecycle_hooks.py").is_file(),
            (runtime / "vllm/v1/engine/request_lifecycle_hooks.py").is_file(),
            True,
            "six_path_general_lifecycle_hook_missing",
        ),
        Check(
            "request_resource_ownership_wiring",
            all(ownership_wiring.values()),
            ownership_wiring,
            {
                "kv_capacity_lease": True,
                "offload_transfer": True,
                "fatal_invalidation": True,
            },
            "request_resource_ownership_wiring_missing",
        ),
        Check(
            "model_snapshot_complete",
            (model_path / "config.json").is_file()
            and (model_path / "model.safetensors.index.json").is_file()
            and all(
                (model_path / f"model-{index:05d}-of-00008.safetensors").is_file()
                for index in range(1, 9)
            ),
            str(model_path),
            "complete local Qwen2.5-14B-Instruct snapshot",
            "model_snapshot_incomplete",
        ),
    ]
    blockers = [check.blocker for check in checks if not check.passed and check.blocker]
    return {
        "schema_version": "issue19-serving-readiness/v1",
        "evidence_class": "smoke-only",
        "service_started": False,
        "real_online_evidence": False,
        "profiler": (
            {
                "path": str(profiler.resolve()),
                "commit": _git_head(profiler),
                "worktree_clean": profiler_clean,
            }
            if profiler is not None
            else None
        ),
        "runtime": {
            "path": str(runtime.resolve()),
            "commit": _git_head(runtime),
            "version": asdict(runtime_version),
            "torch_requirement": runtime_torch,
            "carrier_mode": "empty",
            "worktree_clean": runtime_clean,
        },
        "ascend": {
            "path": str(ascend.resolve()),
            "commit": _git_head(ascend),
            "version": asdict(ascend_version),
            "torch_requirement": ascend_torch,
            "torch_npu_requirement": ascend_torch_npu,
            "documented_vllm_version": ascend_documented_vllm,
            "worktree_clean": ascend_clean,
        },
        "python_environment": python_environment,
        "source_compatibility": source_compatibility,
        "ascend_kv_cache_compatibility": ascend_kv_cache_compatibility,
        "kv_capacity_gate": kv_capacity_gate,
        "compatibility_notes": [
            "The runtime pyproject Torch pin is a build-isolation input.",
            "Ascend owns the serving Torch/Torch-NPU stack; vLLM is installed as an empty carrier.",
            "VLLM_VERSION is set to the paired release for Ascend's documented compatibility gates.",
        ],
        "model_path": str(model_path.resolve()),
        "target": target_configuration(),
        "checks": [asdict(check) for check in checks],
        "blockers": blockers,
        "ready_for_service_smoke": not blockers,
        "service_initialization_verified": False,
        "ready_for_m0": False,
    }


def target_configuration() -> dict[str, Any]:
    return {
        "target_class": "specialty-target",
        "model": TARGET_MODEL,
        "dtype": TARGET_DTYPE,
        "tensor_parallel_size": 1,
        "max_model_len": TARGET_MAX_MODEL_LEN,
        "enforce_eager": True,
        "kv_cache_memory_bytes": TARGET_KV_CACHE_MEMORY_BYTES,
        "connector": TARGET_CONNECTOR,
        "offloading_spec": TARGET_OFFLOADING_SPEC,
        "cpu_offload_bytes": TARGET_CPU_OFFLOAD_BYTES,
        "lifecycle_reconcile": False,
    }


def inspect_service_smoke_result(path: Path | None) -> dict[str, Any]:
    """Validate a separately produced real-service smoke result."""

    if path is None:
        return {
            "passed": False,
            "initialization_passed": False,
            "lifecycle_trace_complete": False,
            "reason": "service_smoke_result_not_provided",
        }
    if not path.is_file():
        return {
            "passed": False,
            "initialization_passed": False,
            "lifecycle_trace_complete": False,
            "reason": "service_smoke_result_missing",
            "path": str(path),
        }
    try:
        result = json.loads(path.read_text())
    except Exception as exc:  # noqa: BLE001 - converted into a fail-closed result.
        return {
            "passed": False,
            "initialization_passed": False,
            "lifecycle_trace_complete": False,
            "reason": f"invalid_service_smoke_result: {type(exc).__name__}: {exc}",
            "path": str(path),
        }

    expected = target_configuration()
    resolved = result.get("resolved_configuration")
    target_matches = isinstance(resolved, Mapping) and all(
        resolved.get(key) == value for key, value in expected.items()
    )
    initialization_checks = {
        "schema": result.get("schema_version") == "issue19-service-smoke/v1",
        "evidence_class": result.get("evidence_class") == "smoke-only",
        "service_started": result.get("service_started") is True,
        "health": result.get("health", {}).get("http_status") == 200,
        "connector_initialized": result.get("connector_initialized") is True,
        "target_configuration": target_matches,
    }
    trace = result.get("trace_validation", {})
    trace_checks = {
        "request_terminal_complete": trace.get("request_terminal_complete") is True,
        "recovery_chain_complete": trace.get("recovery_chain_complete") is True,
        "dropped_data_count_zero": trace.get("dropped_data_count") == 0,
        "writer_failure_count_zero": trace.get("writer_failure_count") == 0,
    }
    initialization_passed = all(initialization_checks.values())
    lifecycle_trace_complete = all(trace_checks.values())
    return {
        "passed": initialization_passed and lifecycle_trace_complete,
        "initialization_passed": initialization_passed,
        "lifecycle_trace_complete": lifecycle_trace_complete,
        "path": str(path.resolve()),
        "initialization_checks": initialization_checks,
        "trace_checks": trace_checks,
    }


def finalize_readiness(
    readiness: dict[str, Any], service_smoke: Mapping[str, Any]
) -> None:
    """Keep smoke admission separate from the later M0 admission gate."""

    blockers = list(dict.fromkeys(readiness.get("blockers", [])))
    readiness["blockers"] = blockers
    readiness["ready_for_service_smoke"] = not blockers
    readiness["service_smoke"] = dict(service_smoke)
    readiness["service_initialization_verified"] = bool(
        service_smoke.get("initialization_passed")
    )
    m0_blockers = list(blockers)
    if not service_smoke.get("initialization_passed"):
        m0_blockers.append("service_smoke_initialization_not_verified")
    if not service_smoke.get("lifecycle_trace_complete"):
        m0_blockers.append("service_smoke_lifecycle_trace_incomplete")
    readiness["m0_blockers"] = list(dict.fromkeys(m0_blockers))
    readiness["ready_for_m0"] = not readiness["m0_blockers"]


def build_execution_manifest(projection: Mapping[str, Any]) -> dict[str, Any]:
    if projection.get("data_revision") != OASST1_REVISION:
        raise ValueError("projection does not use the pinned OASST1 revision")
    rows = projection.get("requests")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise TypeError("projection requests are missing")
    grouped: dict[int, list[Mapping[str, Any]]] = {index: [] for index in range(10)}
    for row in rows:
        if not isinstance(row, Mapping):
            raise TypeError("projection request row is invalid")
        repetition = row.get("repetition")
        if repetition not in grouped:
            raise ValueError("projection repetition is outside 0..9")
        grouped[repetition].append(row)

    lifecycles = []
    for repetition, seed in enumerate(SEEDS):
        requests = sorted(grouped[repetition], key=lambda row: row["ordinal"])
        if len(requests) != 64 or [row["ordinal"] for row in requests] != list(
            range(64)
        ):
            raise ValueError(f"repetition {repetition} is not an exact 64-request set")
        targets = {
            scenario: requests[ordinal]["request_id"]
            for scenario, ordinal in SCENARIO_TARGET_ORDINALS.items()
        }
        lifecycles.append(
            {
                "repetition": repetition,
                "seed": seed,
                "service_lifecycle": f"issue19-m0-{seed}",
                "request_ids": [row["request_id"] for row in requests],
                "scenario_order": list(SCENARIO_ORDER),
                "scenario_targets": targets,
                "unaffected_survivor_request_ids": [
                    row["request_id"] for row in requests[6:]
                ],
                "worker_exit_is_final_action": True,
            }
        )
    return {
        "schema_version": "issue19-m0-execution-plan/v1",
        "status": "preflight-only",
        "evidence_class": "smoke-only",
        "intended_formal_evidence_class": "real-online",
        "observer_only": True,
        "lifecycle_reconcile": False,
        "treatment_implemented": False,
        "service_lifecycle_count": 10,
        "requests_per_lifecycle": 64,
        "client_timeout_seconds": 2.0,
        "quiescence_stable_seconds": 5,
        "quiescence_timeout_seconds": 120,
        "communication_mode": "issue2:kv-recovery-v1alpha1",
        "target": target_configuration(),
        "scenario_semantics": {
            "normal_completion": "complete one request through the real OpenAI route",
            "client_disconnect": "close the real streaming HTTP connection",
            "client_timeout": "enforce a 2.0 second client deadline",
            "duplicate_cancel": "call the same real AsyncLLM.abort identity twice",
            "recovery": "observe naturally triggered preemption and remote-KV recovery",
            "worker_exit": "kill only a verified child worker of this service, last",
        },
        "safety": {
            "endpoint_scope": "loopback-only",
            "worker_pid_must_be_owned_descendant": True,
            "npu_must_be_idle": True,
            "stop_if_preflight_blocked": True,
            "serving_callbacks": "fail-open",
            "evidence_validation": "fail-closed",
        },
        "lifecycles": lifecycles,
    }


def inspect_context_gate(
    repetitions: Sequence[Sequence[Any]],
    model_path: Path,
    *,
    max_model_len: int = TARGET_MAX_MODEL_LEN,
) -> dict[str, Any]:
    """Run the pre-registered tokenizer gate against the local model snapshot."""

    try:
        from transformers import AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
        result = preflight_context_lengths(
            repetitions, tokenizer, max_model_len=max_model_len
        )
    except Exception as exc:  # noqa: BLE001 - converted into a fail-closed blocker.
        return {
            "passed": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {"passed": True, **asdict(result)}


def write_preflight_outputs(
    output_dir: Path,
    *,
    projection: Mapping[str, Any],
    execution: Mapping[str, Any],
    readiness: Mapping[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for stale in (
        output_dir / "READY.txt",
        output_dir / "BLOCKED.txt",
        output_dir / "SMOKE_READY.txt",
        output_dir / "M0_BLOCKED.txt",
    ):
        stale.unlink(missing_ok=True)
    for name, value in (
        ("projection_manifest.json", projection),
        ("execution_manifest.json", execution),
        ("environment_manifest.json", readiness),
    ):
        (output_dir / name).write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    blockers = readiness.get("blockers", [])
    if blockers:
        message = "BLOCKED: service smoke was not started.\n" + "".join(
            f"- {blocker}\n" for blocker in blockers
        )
        (output_dir / "BLOCKED.txt").write_text(message, encoding="utf-8")
    else:
        (output_dir / "SMOKE_READY.txt").write_text(
            "SMOKE_READY: static gates passed; a real service smoke may start.\n",
            encoding="utf-8",
        )
    m0_blockers = readiness.get("m0_blockers", blockers)
    if readiness.get("ready_for_m0") is True:
        (output_dir / "READY.txt").write_text(
            "READY_FOR_M0: executable target and real service smoke passed.\n",
            encoding="utf-8",
        )
    else:
        message = "M0_BLOCKED: formal M0 must not start.\n" + "".join(
            f"- {blocker}\n" for blocker in m0_blockers
        )
        (output_dir / "M0_BLOCKED.txt").write_text(message, encoding="utf-8")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the fixed Issue #19 plan and fail-closed serving preflight."
    )
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--ascend", type=Path, default=DEFAULT_ASCEND)
    parser.add_argument("--runtime-python", type=Path, default=Path(sys.executable))
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--service-smoke-result",
        type=Path,
        help="Machine-readable result from a separately run real NPU service smoke.",
    )
    parser.add_argument(
        "--oasst1-data",
        type=Path,
        default=DEFAULT_DATA_CACHE / OASST1_FILENAME,
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    repetitions = build_oasst1_repetitions(args.oasst1_data)
    projection = build_projection_manifest(repetitions)
    execution = build_execution_manifest(projection)
    readiness = inspect_serving_readiness(
        profiler=REPO_ROOT,
        runtime=args.runtime,
        ascend=args.ascend,
        runtime_python=args.runtime_python,
        model_path=args.model_path,
    )
    context_gate = inspect_context_gate(
        repetitions, args.model_path, max_model_len=TARGET_MAX_MODEL_LEN
    )
    readiness["context_gate"] = context_gate
    if not context_gate["passed"]:
        readiness["checks"].append(
            asdict(
                Check(
                    "oasst1_context_gate",
                    False,
                    context_gate.get("error"),
                    (
                        "all 640 requests fit "
                        f"max_model_len={TARGET_MAX_MODEL_LEN} without truncation"
                    ),
                    "oasst1_context_gate_failed",
                )
            )
        )
        readiness["blockers"].append("oasst1_context_gate_failed")
    service_smoke = inspect_service_smoke_result(args.service_smoke_result)
    finalize_readiness(readiness, service_smoke)
    write_preflight_outputs(
        args.output_dir,
        projection=projection,
        execution=execution,
        readiness=readiness,
    )
    if readiness["blockers"]:
        print(json.dumps({"status": "BLOCKED", "blockers": readiness["blockers"]}))
        return 2
    print(
        json.dumps(
            {
                "status": "SMOKE_READY",
                "ready_for_m0": readiness["ready_for_m0"],
                "m0_blockers": readiness["m0_blockers"],
                "output_dir": str(args.output_dir),
            }
        )
    )
    return 0


__all__ = [
    "SCENARIO_ORDER",
    "SCENARIO_TARGET_ORDINALS",
    "SEEDS",
    "build_execution_manifest",
    "collect_python_environment",
    "finalize_readiness",
    "inspect_context_gate",
    "inspect_kv_capacity_gate",
    "inspect_service_smoke_result",
    "inspect_serving_readiness",
    "main",
    "probe_ascend_kv_cache_compatibility",
    "target_configuration",
    "write_preflight_outputs",
]


if __name__ == "__main__":
    raise SystemExit(main())
