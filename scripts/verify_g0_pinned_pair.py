"""CPU-only source-contract probe for the approved vLLM/Ascend pair.

This probe deliberately reads committed Git blobs instead of either sibling
worktree.  It can prove pinned source and controlled-stub handoff contracts, but it
cannot turn a missing exact runtime import environment into a GO.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import math
import subprocess
import sys
import types
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

RUNTIME_COMMIT = "f229ba7cad21a4dba58681af6738a9fd947388e2"
DEVICE_COMMIT = "cafad89a5e103f31ea517c1edb56130578c3cd56"
PROFILE_ID = "rlp.kv-recovery/v1alpha1"
BENCHMARK_134_INCOMPLETE_CANDIDATE_SHA256 = (
    "b57fed50aa067e937728fe6f618a37246c50becd5ac94bd8eef3bc2ee7184b3a"
)
BENCHMARK_134_INCOMPLETE_CANDIDATE_CANONICAL_SHA256 = (
    "d6520a785d566b6509532c59de01c33abdee7ebbfee41f1cba76c42b695dc54d"
)

RUNTIME_BLOBS = {
    "vllm/config/scheduler.py": (
        "a816cf79a3e74ffc0984f9bebb274275b26f46be8b28cb77a29388a0996263c8"
    ),
    "vllm/v1/core/sched/interface.py": (
        "abee13a3d933224d4ff7575e6796171f8b2bb1b5948b95a996f99e48c1f12a1f"
    ),
    "vllm/v1/core/sched/scheduler.py": (
        "77d4fa21d3b5b8341c7dbbd85d10bcefc650e2ad6e8224a241150c096721ecec"
    ),
    "vllm/v1/core/sched/async_scheduler.py": (
        "da6343d7e7c394a1738cf72905cbecc208003ffa461ccb441268333a3eb9f884"
    ),
    "vllm/v1/engine/core.py": (
        "d1b90a2c0ae07571b28c458c7fb7d3a785c6244cdfa8f4808e96de8ba0e96800"
    ),
    "vllm/distributed/kv_transfer/kv_connector/factory.py": (
        "00dfbc3e6c9472bbeab63ba3a9d93d5b1d49e66a306a189d3d0996a935b6532a"
    ),
    "vllm/distributed/kv_transfer/kv_connector/v1/offloading/worker.py": (
        "72266e41fb0dd7fcc667f5c4dafe984a2dca716fb15cd86276a10e9f11415063"
    ),
    "vllm/distributed/kv_transfer/kv_connector/v1/offloading_connector.py": (
        "9b66cfd9b83b419ee55389cee50896bd91d299f8da830cc66ad1dbafa00acf27"
    ),
    "vllm/v1/kv_offload/factory.py": (
        "97eea8c98e3e4ebef0d0cd35df3f9f187d6234fc6b4ab3a58a604b208840fe2b"
    ),
    "vllm/v1/kv_offload/cpu/spec.py": (
        "04379c5a3b67f40558ceb901e35df15c6e8b445fc749772468f986b5f03cea80"
    ),
    "vllm/v1/kv_offload/cpu/npu_worker.py": (
        "2e630269ddb8a3aa3262b6dc2d32709114196f1d71c176e44834b9aeb66821a5"
    ),
    "vllm/v1/kv_offload/cpu/worker_factory.py": (
        "9c2770e1857941f4f872b47fb99a22b847a21780e23135557d0f762821152d0c"
    ),
    "vllm/v1/kv_offload/tiering/spec.py": (
        "00442f770fe1cf8666be3c2468b69481451c19bea94948165e020339ca9eb97f"
    ),
}

DEVICE_BLOBS = {
    "vllm_ascend/ascend_config.py": (
        "cf9d823da665f79d8f669fe216e28a51697d6ffa98b01b55ba6c75e77a9a00c2"
    ),
    "vllm_ascend/platform.py": (
        "1b4c3d8000a2d5474ad5348adf17919207be6242312cd24054b10cd18d5bc1f3"
    ),
    "vllm_ascend/core/recompute_scheduler.py": (
        "2d723b3796143764c6d4516650208b4d0f039cd9b7be07e724ad1b90a462f83b"
    ),
    "vllm_ascend/core/scheduler_dynamic_batch.py": (
        "5ce092eeb1f6ab33291314c482cf23ec4ace1b07d17f5a8e80fa1af6a3e2181f"
    ),
    "vllm_ascend/kv_offload/npu.py": (
        "4ceedc991511e2cde1b52735c48294e7f3faa2608fe8e2501b6a13160ebe417d"
    ),
    "vllm_ascend/distributed/kv_transfer/__init__.py": (
        "8d6fd27460a0288a3b2dea9043431e3a3fe5c6abee82d721aa2154aaef5fec99"
    ),
}

EXIT_FAILED = 1
EXIT_BLOCKED = 2


class ProbeFailure(RuntimeError):
    """A source-contract or fake-handoff assertion failed."""


@dataclass(frozen=True)
class GitBlobRepository:
    path: Path
    commit: str

    def _run(
        self, *args: str, check: bool = True
    ) -> subprocess.CompletedProcess[bytes]:
        result = subprocess.run(
            ["git", "-C", str(self.path), *args],
            check=False,
            capture_output=True,
        )
        if check and result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            raise ProbeFailure(f"git {' '.join(args)} failed in {self.path}: {stderr}")
        return result

    def verify_commit(self) -> None:
        object_type = self._run("cat-file", "-t", self.commit).stdout.strip()
        if object_type != b"commit":
            raise ProbeFailure(f"{self.commit} is not a commit in {self.path}")

    def blob(self, relative_path: str) -> bytes:
        return self._run("show", f"{self.commit}:{relative_path}").stdout

    def source(self, relative_path: str) -> str:
        raw = self.blob(relative_path)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProbeFailure(f"non-UTF-8 Python blob: {relative_path}") from exc

    def path_exists(self, relative_path: str) -> bool:
        result = self._run(
            "cat-file", "-e", f"{self.commit}:{relative_path}", check=False
        )
        return result.returncode == 0


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise ProbeFailure(message)


def _parse(source: str, label: str) -> ast.Module:
    try:
        return ast.parse(source, filename=label)
    except SyntaxError as exc:
        raise ProbeFailure(f"cannot parse pinned source {label}: {exc}") from exc


def _class_method(
    tree: ast.Module, class_name: str, method_name: str
) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == method_name:
                    return child
    raise ProbeFailure(f"missing {class_name}.{method_name}")


def _method_shape(method: ast.FunctionDef) -> tuple[list[str], list[str]]:
    positional = [
        argument.arg for argument in (*method.args.posonlyargs, *method.args.args)
    ]
    defaults = [ast.unparse(value) for value in method.args.defaults]
    return positional, defaults


def _literal_registrations(
    tree: ast.Module, receiver: str, method_name: str
) -> dict[str, tuple[str, str]]:
    registrations: dict[str, tuple[str, str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != method_name or not isinstance(node.func.value, ast.Name):
            continue
        if node.func.value.id != receiver or len(node.args) != 3:
            continue
        try:
            name, module_path, class_name = (
                ast.literal_eval(argument) for argument in node.args
            )
        except (ValueError, TypeError):
            continue
        if all(isinstance(value, str) for value in (name, module_path, class_name)):
            registrations[name] = (module_path, class_name)
    return registrations


def _assigned_dict_get_default(
    tree: ast.Module, class_name: str, target_attribute: str
) -> Any:
    init = _class_method(tree, class_name, "__init__")
    for node in ast.walk(init):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
            and target.attr == target_attribute
        ):
            continue
        value = node.value
        if not (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Attribute)
            and isinstance(value.func.value, ast.Name)
            and value.func.value.id == "additional_config"
            and value.func.attr == "get"
            and len(value.args) == 2
        ):
            raise ProbeFailure(
                f"{class_name}.{target_attribute} is not an explicit dict.get"
            )
        return ast.literal_eval(value.args[1])
    raise ProbeFailure(f"missing assignment to {class_name}.{target_attribute}")


def _load_and_fingerprint(
    repository: GitBlobRepository, expected: dict[str, str]
) -> dict[str, str]:
    repository.verify_commit()
    sources: dict[str, str] = {}
    for relative_path, expected_sha256 in expected.items():
        raw = repository.blob(relative_path)
        observed = hashlib.sha256(raw).hexdigest()
        _assert(
            observed == expected_sha256,
            f"SHA-256 mismatch for {repository.commit}:{relative_path}",
        )
        try:
            source = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProbeFailure(f"non-UTF-8 source: {relative_path}") from exc
        _parse(source, f"{repository.commit}:{relative_path}")
        sources[relative_path] = source
    return sources


def verify_scheduler_contract(
    runtime_sources: dict[str, str], device_sources: dict[str, str]
) -> dict[str, Any]:
    interface = _parse(
        runtime_sources["vllm/v1/core/sched/interface.py"], "scheduler interface"
    )
    scheduler = _parse(
        runtime_sources["vllm/v1/core/sched/scheduler.py"], "runtime scheduler"
    )
    async_scheduler = _parse(
        runtime_sources["vllm/v1/core/sched/async_scheduler.py"],
        "runtime async scheduler",
    )
    recompute = _parse(
        device_sources["vllm_ascend/core/recompute_scheduler.py"],
        "device recompute scheduler",
    )
    dynamic = _parse(
        device_sources["vllm_ascend/core/scheduler_dynamic_batch.py"],
        "device dynamic scheduler",
    )

    runtime_interface_shape = _method_shape(
        _class_method(interface, "SchedulerInterface", "schedule")
    )
    runtime_scheduler_shape = _method_shape(
        _class_method(scheduler, "Scheduler", "schedule")
    )
    recompute_shape = _method_shape(
        _class_method(recompute, "RecomputeScheduler", "schedule")
    )
    dynamic_shape = _method_shape(
        _class_method(dynamic, "SchedulerDynamicBatch", "schedule")
    )
    expected_runtime_shape = (["self", "throttle_prefills"], ["False"])
    _assert(
        runtime_interface_shape == expected_runtime_shape,
        f"unexpected SchedulerInterface.schedule shape: {runtime_interface_shape}",
    )
    _assert(
        runtime_scheduler_shape == expected_runtime_shape,
        f"unexpected Scheduler.schedule shape: {runtime_scheduler_shape}",
    )
    async_classes = [
        node
        for node in async_scheduler.body
        if isinstance(node, ast.ClassDef) and node.name == "AsyncScheduler"
    ]
    _assert(len(async_classes) == 1, "missing unique AsyncScheduler class")
    async_class = async_classes[0]
    _assert(
        len(async_class.bases) == 1
        and isinstance(async_class.bases[0], ast.Name)
        and async_class.bases[0].id == "Scheduler",
        "AsyncScheduler no longer directly inherits runtime Scheduler",
    )
    _assert(
        not any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "schedule"
            for node in async_class.body
        ),
        "AsyncScheduler now overrides schedule; repeat interface review",
    )
    _assert(
        recompute_shape == (["self"], []),
        "RecomputeScheduler is no longer the expected incompatible negative control",
    )
    _assert(
        dynamic_shape == (["self"], []),
        "SchedulerDynamicBatch is no longer the expected incompatible negative control",
    )

    core = _parse(runtime_sources["vllm/v1/engine/core.py"], "engine core")
    schedule_calls: list[ast.Call] = []
    for node in ast.walk(core):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        owner = node.func.value
        if not (
            node.func.attr == "schedule"
            and isinstance(owner, ast.Attribute)
            and owner.attr == "scheduler"
            and isinstance(owner.value, ast.Name)
            and owner.value.id == "self"
        ):
            continue
        schedule_calls.append(node)
    _assert(
        len(schedule_calls) == 2, "EngineCore must have exactly two scheduler calls"
    )
    for call in schedule_calls:
        _assert(len(call.args) == 1 and not call.keywords, "unexpected schedule call")
        argument = call.args[0]
        _assert(
            isinstance(argument, ast.Call)
            and isinstance(argument.func, ast.Attribute)
            and isinstance(argument.func.value, ast.Name)
            and argument.func.value.id == "self"
            and argument.func.attr == "_should_throttle_prefills"
            and not argument.args
            and not argument.keywords,
            "EngineCore does not pass the exact throttle-prefills call",
        )

    ascend_config = _parse(
        device_sources["vllm_ascend/ascend_config.py"], "AscendConfig"
    )
    recompute_default = _assigned_dict_get_default(
        ascend_config, "AscendConfig", "recompute_scheduler_enable"
    )
    dynamic_default = _assigned_dict_get_default(
        ascend_config, "AscendConfig", "SLO_limits_for_dynamic_batch"
    )
    _assert(recompute_default is False, "recompute scheduler default changed")
    _assert(dynamic_default == -1, "dynamic scheduler default changed")

    platform = _parse(device_sources["vllm_ascend/platform.py"], "Ascend platform")
    platform_text = ast.unparse(platform)
    _assert(
        "if ascend_config.recompute_scheduler_enable:" in platform_text
        and "RecomputeSchedulerConfig.initialize_from_config" in platform_text,
        "recompute scheduler installation guard changed",
    )
    _assert(
        "if ascend_config.SLO_limits_for_dynamic_batch != -1:" in platform_text
        and "vllm_ascend.core.scheduler_dynamic_batch.SchedulerDynamicBatch"
        in platform_text,
        "dynamic scheduler installation guard changed",
    )

    scheduler_config = _parse(
        runtime_sources["vllm/config/scheduler.py"], "SchedulerConfig"
    )
    get_scheduler_cls = _class_method(
        scheduler_config, "SchedulerConfig", "get_scheduler_cls"
    )
    _assert(
        "from vllm.v1.core.sched.scheduler import Scheduler"
        in ast.unparse(get_scheduler_cls),
        "runtime default scheduler resolution changed",
    )
    return {
        "engine_core_call_lines": [call.lineno for call in schedule_calls],
        "runtime_schedule_shape": runtime_scheduler_shape,
        "async_scheduler_schedule_resolution": "inherits_runtime_Scheduler",
        "incompatible_device_schedule_shapes": {
            "RecomputeScheduler": recompute_shape,
            "SchedulerDynamicBatch": dynamic_shape,
        },
        "required_resolved_guards": {
            "recompute_scheduler_enable": False,
            "SLO_limits_for_dynamic_batch": -1,
            "scheduler_cls": None,
        },
    }


def verify_factory_contract(
    runtime_sources: dict[str, str], device_sources: dict[str, str]
) -> dict[str, Any]:
    connector_factory = _parse(
        runtime_sources["vllm/distributed/kv_transfer/kv_connector/factory.py"],
        "connector factory",
    )
    connector_registrations = _literal_registrations(
        connector_factory, "KVConnectorFactory", "register_connector"
    )
    expected_connector = (
        "vllm.distributed.kv_transfer.kv_connector.v1.offloading_connector",
        "OffloadingConnector",
    )
    _assert(
        connector_registrations.get("OffloadingConnector") == expected_connector,
        "runtime OffloadingConnector registry entry changed",
    )

    spec_factory = _parse(
        runtime_sources["vllm/v1/kv_offload/factory.py"], "offloading spec factory"
    )
    spec_registrations = _literal_registrations(
        spec_factory, "OffloadingSpecFactory", "register_spec"
    )
    expected_spec = (
        "vllm.v1.kv_offload.tiering.spec",
        "TieringOffloadingSpec",
    )
    _assert(
        spec_registrations.get("TieringOffloadingSpec") == expected_spec,
        "runtime TieringOffloadingSpec registry entry changed",
    )

    device_connectors = _parse(
        device_sources["vllm_ascend/distributed/kv_transfer/__init__.py"],
        "device connector registrations",
    )
    device_registrations = _literal_registrations(
        device_connectors, "KVConnectorFactory", "register_connector"
    )
    _assert(
        "OffloadingConnector" not in device_registrations,
        "device plugin unexpectedly overrides OffloadingConnector",
    )
    for node in ast.walk(device_connectors):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "pop" or not node.args:
            continue
        try:
            popped = ast.literal_eval(node.args[0])
        except (ValueError, TypeError):
            continue
        _assert(
            popped != "OffloadingConnector",
            "device plugin removes the runtime OffloadingConnector registration",
        )

    worker_factory = _parse(
        runtime_sources["vllm/v1/kv_offload/cpu/worker_factory.py"],
        "runtime worker factory",
    )
    worker_factory_text = ast.unparse(worker_factory)
    _assert(
        "from vllm.v1.kv_offload.cpu.npu_worker import AscendCPUOffloadingWorker"
        in worker_factory_text,
        "runtime worker factory no longer owns the Ascend offloading worker path",
    )
    _assert(
        "if is_ascend_platform():" in worker_factory_text,
        "runtime worker factory Ascend guard changed",
    )

    connector_impl = _parse(
        runtime_sources[
            "vllm/distributed/kv_transfer/kv_connector/v1/offloading_connector.py"
        ],
        "runtime offloading connector",
    )
    connector_impl_text = ast.unparse(connector_impl)
    _assert(
        "class OffloadingConnector(KVConnectorBase_V1, SupportsHMA):"
        in connector_impl_text,
        "runtime OffloadingConnector implementation shape changed",
    )
    _assert(
        "OffloadingConnectorWorker(spec)" in connector_impl_text,
        "runtime connector no longer constructs its pinned worker",
    )

    cpu_spec = _parse(
        runtime_sources["vllm/v1/kv_offload/cpu/spec.py"], "runtime CPU spec"
    )
    cpu_spec_text = ast.unparse(cpu_spec)
    _assert(
        "cpu_bytes_to_use = self.extra_config.get('cpu_bytes_to_use')" in cpu_spec_text
        and "if not cpu_bytes_to_use:" in cpu_spec_text,
        "CPUOffloadingSpec cpu_bytes_to_use requirement changed",
    )

    tiering_spec = _parse(
        runtime_sources["vllm/v1/kv_offload/tiering/spec.py"],
        "runtime tiering spec",
    )
    tiering_spec_text = ast.unparse(tiering_spec)
    _assert(
        "class TieringOffloadingSpec(CPUOffloadingSpec):" in tiering_spec_text,
        "TieringOffloadingSpec no longer inherits CPUOffloadingSpec",
    )
    _assert(
        "secondary_tiers" in tiering_spec_text
        and "tiering_use_pinned_cpu_primary" in tiering_spec_text,
        "TieringOffloadingSpec selected primary-tier resolution changed",
    )

    npu_worker = _parse(
        runtime_sources["vllm/v1/kv_offload/cpu/npu_worker.py"],
        "runtime Ascend CPU offloading worker",
    )
    _assert(
        any(
            isinstance(node, ast.ClassDef) and node.name == "AscendCPUOffloadingWorker"
            for node in npu_worker.body
        ),
        "runtime AscendCPUOffloadingWorker implementation is missing",
    )
    return {
        "connector": expected_connector,
        "spec": expected_spec,
        "ascend_worker": "vllm.v1.kv_offload.cpu.npu_worker.AscendCPUOffloadingWorker",
        "device_connector_override": False,
        "selected_implementation_blobs_parsed": [
            "offloading_connector.py",
            "cpu/spec.py",
            "tiering/spec.py",
            "cpu/npu_worker.py",
            "core/sched/async_scheduler.py",
        ],
    }


def verify_legacy_npu_negative_control(
    runtime_repository: GitBlobRepository, device_sources: dict[str, str]
) -> dict[str, Any]:
    legacy_module = "vllm.v1.kv_offload.worker.worker"
    legacy_path = "vllm/v1/kv_offload/worker/worker.py"
    npu_tree = _parse(
        device_sources["vllm_ascend/kv_offload/npu.py"], "device npu spec"
    )
    imports = {
        node.module
        for node in ast.walk(npu_tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    _assert(legacy_module in imports, "device legacy negative-control import changed")
    _assert(
        not runtime_repository.path_exists(legacy_path),
        "legacy runtime module unexpectedly exists; repeat compatibility review",
    )
    return {
        "device_import": legacy_module,
        "runtime_path": legacy_path,
        "runtime_path_exists": False,
        "meaning": "device NPU spec remains an incompatible negative control",
    }


class _Tensor:
    pass


class _AttentionBackend:
    pass


class _AttentionSpec:
    pass


class _MambaSpec:
    pass


class _UniformTypeKVCacheSpecs:
    pass


class _CanonicalKVCacheRef:
    pass


class _CanonicalKVCaches:
    pass


class _CanonicalKVCacheTensor:
    pass


class _LoadStoreSpec:
    pass


class _GPULoadStoreSpec(_LoadStoreSpec):
    pass


class _OffloadingSpec:
    pass


class _OffloadingWorker:
    pass


class _DirectionalStats:
    def __init__(self) -> None:
        self.records: list[tuple[int, float]] = []

    def record(self, size: int, duration: float) -> None:
        self.records.append((size, duration))


class _TransferStats:
    def __init__(self) -> None:
        self.load = _DirectionalStats()
        self.store = _DirectionalStats()


class _OffloadingWorkerMetadata:
    def __init__(self) -> None:
        self.completed_jobs: dict[int, int] = {}
        self.transfer_stats = _TransferStats()

    def mark_completed(self, job_id: int) -> None:
        self.completed_jobs[job_id] = 1


@dataclass
class _TransferJob:
    req_id: str
    src_spec: object
    dst_spec: object


@dataclass
class _OffloadingConnectorMetadata:
    load_jobs: dict[int, _TransferJob]
    store_jobs: dict[int, _TransferJob]
    jobs_to_flush: set[int] | None = None


@dataclass(frozen=True)
class _TransferResult:
    job_id: int
    success: bool
    transfer_size: int | None = None
    transfer_time: float | None = None


class _NullLogger:
    def __getattr__(self, _name: str) -> Callable[..., None]:
        return lambda *_args, **_kwargs: None


@contextmanager
def _temporary_modules(modules: dict[str, types.ModuleType]) -> Iterator[None]:
    missing = object()
    previous: dict[str, object] = {
        name: sys.modules.get(name, missing) for name in modules
    }
    sys.modules.update(modules)
    try:
        yield
    finally:
        for name, old_value in previous.items():
            if old_value is missing:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old_value  # type: ignore[assignment]


def _stub_module(name: str, **attributes: object) -> types.ModuleType:
    module = types.ModuleType(name)
    for attribute, value in attributes.items():
        setattr(module, attribute, value)
    return module


def _load_pinned_worker_class(source: str) -> type[Any]:
    modules = {
        "torch": _stub_module("torch", Tensor=_Tensor, int8=object()),
        "vllm.distributed.kv_transfer.kv_connector.v1.offloading.common": (
            _stub_module(
                "vllm.distributed.kv_transfer.kv_connector.v1.offloading.common",
                OffloadingConnectorMetadata=_OffloadingConnectorMetadata,
                OffloadingWorkerMetadata=_OffloadingWorkerMetadata,
                ReqId=str,
            )
        ),
        "vllm.logger": _stub_module(
            "vllm.logger", init_logger=lambda _name: _NullLogger()
        ),
        "vllm.v1.attention.backend": _stub_module(
            "vllm.v1.attention.backend", AttentionBackend=_AttentionBackend
        ),
        "vllm.v1.kv_cache_interface": _stub_module(
            "vllm.v1.kv_cache_interface",
            AttentionSpec=_AttentionSpec,
            MambaSpec=_MambaSpec,
            UniformTypeKVCacheSpecs=_UniformTypeKVCacheSpecs,
        ),
        "vllm.v1.kv_offload.base": _stub_module(
            "vllm.v1.kv_offload.base",
            CanonicalKVCacheRef=_CanonicalKVCacheRef,
            CanonicalKVCaches=_CanonicalKVCaches,
            CanonicalKVCacheTensor=_CanonicalKVCacheTensor,
            GPULoadStoreSpec=_GPULoadStoreSpec,
            LoadStoreSpec=_LoadStoreSpec,
            OffloadingSpec=_OffloadingSpec,
            OffloadingWorker=_OffloadingWorker,
        ),
    }
    pinned_module = types.ModuleType("_g0_pinned_offloading_worker")
    with _temporary_modules(modules):
        exec(  # noqa: S102 - exact audited Git blob executed with controlled stubs
            compile(source, "git:pinned-offloading-worker.py", "exec"),
            pinned_module.__dict__,
        )
    worker_class = getattr(pinned_module, "OffloadingConnectorWorker", None)
    _assert(isinstance(worker_class, type), "pinned worker class did not load")
    return worker_class


@dataclass(frozen=True)
class _RecoveryIdentity:
    run_id: str
    process_uuid: str
    trace_id: str
    lifecycle_id: str
    runtime_request_id: str
    recovery_epoch: int
    episode_id: str
    transfer_id: str
    rank: int
    direction: str
    logical_blocks: tuple[tuple[int, int, str], ...]
    block_set_id: str


def _block_set_id(identity: _RecoveryIdentity) -> str:
    prefix = (
        PROFILE_ID.encode("ascii")
        + b"\x00"
        + identity.run_id.encode("ascii")
        + b"\x00"
        + identity.lifecycle_id.encode("ascii")
        + b"\x00"
    )
    rows = b"".join(
        f"{group}:{ordinal}:{logical_id}\n".encode("ascii")
        for group, ordinal, logical_id in identity.logical_blocks
    )
    return hashlib.sha256(prefix + rows).hexdigest()


class _HandoffLedger:
    def __init__(self) -> None:
        self._submitted: dict[int, _RecoveryIdentity] = {}
        self._completed: set[int] = set()

    @staticmethod
    def _validate_identity(identity: _RecoveryIdentity) -> None:
        _assert(len(identity.run_id) == 32, "invalid run ID")
        _assert(len(identity.process_uuid) == 32, "invalid process UUID")
        _assert(len(identity.trace_id) == 32, "invalid trace ID")
        _assert(
            identity.lifecycle_id == f"{identity.trace_id}:e:0",
            "lifecycle identity drift",
        )
        _assert(identity.recovery_epoch > 0, "recovery epoch must be positive")
        _assert(
            identity.episode_id
            == f"{identity.lifecycle_id}:k:{identity.recovery_epoch}",
            "episode identity drift",
        )
        _assert(
            identity.transfer_id.startswith(f"{identity.process_uuid}:t:"),
            "transfer/process identity drift",
        )
        _assert(identity.rank == 0 and identity.direction == "h2d", "scope drift")
        _assert(bool(identity.logical_blocks), "logical block set is empty")
        _assert(
            tuple(sorted(identity.logical_blocks)) == identity.logical_blocks,
            "logical blocks are not canonically ordered",
        )
        logical_ids = [row[2] for row in identity.logical_blocks]
        _assert(len(set(logical_ids)) == len(logical_ids), "duplicate logical block")
        _assert(
            identity.block_set_id == _block_set_id(identity),
            "logical block-set digest drift",
        )

    def submit(self, job_id: int, identity: _RecoveryIdentity) -> None:
        self._validate_identity(identity)
        _assert(job_id not in self._submitted, "duplicate transfer submission")
        self._submitted[job_id] = identity

    def complete(
        self,
        job_id: int,
        observed_identity: _RecoveryIdentity,
        result: _TransferResult,
    ) -> int | None:
        expected_identity = self._submitted.get(job_id)
        _assert(expected_identity is not None, "unknown transfer completion")
        _assert(job_id not in self._completed, "duplicate transfer completion")
        self._validate_identity(observed_identity)
        _assert(observed_identity == expected_identity, "handoff identity drift")
        _assert(result.job_id == job_id, "connector job identity drift")
        _assert(result.success, "failed transfer is not a positive handoff")
        _assert(
            result.transfer_size is not None and result.transfer_size > 0,
            "positive transfer bytes are required",
        )
        self._completed.add(job_id)
        transfer_time = result.transfer_time
        if (
            transfer_time is None
            or not math.isfinite(transfer_time)
            or transfer_time <= 0
        ):
            return None
        duration_ns = math.floor(transfer_time * 1_000_000_000 + 0.5)
        _assert(duration_ns < 2**64, "device duration overflows uint64")
        return duration_ns


class _FakeWorkerBackend:
    def __init__(self) -> None:
        self.submitted_loads: list[tuple[int, object, object]] = []
        self.wait_sets: list[set[int]] = []
        self.results: list[_TransferResult] = []
        self.on_results: Callable[[list[_TransferResult]], None] | None = None

    def submit_load(self, job_id: int, src: object, dst: object) -> bool:
        self.submitted_loads.append((job_id, src, dst))
        return True

    def submit_store(self, _job_id: int, _src: object, _dst: object) -> bool:
        raise ProbeFailure("unexpected store in H2D fake")

    def get_finished(self) -> list[_TransferResult]:
        results, self.results = self.results, []
        if self.on_results is not None:
            self.on_results(results)
        return results

    def wait(self, job_ids: set[int]) -> None:
        self.wait_sets.append(set(job_ids))

    def shutdown(self) -> None:
        return


def _make_identity() -> _RecoveryIdentity:
    identity = _RecoveryIdentity(
        run_id="1" * 32,
        process_uuid="2" * 32,
        trace_id="3" * 32,
        lifecycle_id=f"{'3' * 32}:e:0",
        runtime_request_id="g0-opaque-request-0001-suffix",
        recovery_epoch=1,
        episode_id=f"{'3' * 32}:e:0:k:1",
        transfer_id=f"{'2' * 32}:t:0",
        rank=0,
        direction="h2d",
        logical_blocks=((0, 0, "4" * 32), (0, 1, "5" * 32)),
        block_set_id="",
    )
    return replace(identity, block_set_id=_block_set_id(identity))


def _expect_rejection(name: str, operation: Callable[[], None]) -> str:
    try:
        operation()
    except ProbeFailure:
        return name
    raise ProbeFailure(f"negative fake-handoff case was accepted: {name}")


def verify_fake_handoff(worker_source: str) -> dict[str, Any]:
    """Exercise pinned job/request handling plus a separate observer ledger.

    The pinned worker does not carry recovery-profile identity. The ledger
    below is a G0 adapter-design fake and must not be described as runtime
    propagation or G1 wiring.
    """

    worker_class = _load_pinned_worker_class(worker_source)
    runtime_worker = worker_class(_OffloadingSpec())
    backend = _FakeWorkerBackend()
    runtime_worker.worker = backend

    job_id = 7
    identity = _make_identity()
    source_spec = _LoadStoreSpec()
    destination_spec = _GPULoadStoreSpec()
    metadata = _OffloadingConnectorMetadata(
        load_jobs={
            job_id: _TransferJob(
                req_id=identity.runtime_request_id,
                src_spec=source_spec,
                dst_spec=destination_spec,
            )
        },
        store_jobs={},
        jobs_to_flush={job_id},
    )
    runtime_worker.start_kv_transfers(metadata)
    _assert(
        backend.submitted_loads == [(job_id, source_spec, destination_spec)],
        "pinned worker did not preserve the submitted H2D job",
    )

    ledger = _HandoffLedger()
    ledger.submit(job_id, identity)
    result = _TransferResult(
        job_id=job_id,
        success=True,
        transfer_size=8192,
        transfer_time=0.0125,
    )
    observed_durations: list[int | None] = []
    backend.on_results = lambda results: observed_durations.extend(
        ledger.complete(item.job_id, identity, item) for item in results
    )
    backend.results = [result]
    finished_sending, finished_recving = runtime_worker.get_finished(set())
    _assert(finished_sending == set(), "unexpected finished-sending request")
    _assert(
        finished_recving == {identity.runtime_request_id},
        "pinned worker lost the request association",
    )
    _assert(observed_durations == [12_500_000], "seconds-to-ns conversion drift")
    _assert(
        runtime_worker._connector_worker_meta.completed_jobs == {job_id: 1},
        "worker metadata lost connector job identity",
    )
    _assert(
        runtime_worker._connector_worker_meta.transfer_stats.load.records
        == [(8192, 0.0125)],
        "worker transfer statistics drifted",
    )
    runtime_worker.handle_preemptions(metadata)
    _assert(backend.wait_sets == [{job_id}], "worker wait set membership drifted")

    drift_ledger = _HandoffLedger()
    drift_ledger.submit(job_id, identity)
    drifted = replace(identity, runtime_request_id="g0-different-request-suffix")
    block_drift_ledger = _HandoffLedger()
    block_drift_ledger.submit(job_id, identity)
    changed_blocks = replace(
        identity,
        logical_blocks=((0, 0, "6" * 32), (0, 1, "5" * 32)),
        block_set_id="",
    )
    changed_blocks = replace(changed_blocks, block_set_id=_block_set_id(changed_blocks))
    duplicate_ledger = _HandoffLedger()
    duplicate_ledger.submit(job_id, identity)
    duplicate_ledger.complete(job_id, identity, result)
    failed_ledger = _HandoffLedger()
    failed_ledger.submit(job_id, identity)
    zero_size_ledger = _HandoffLedger()
    zero_size_ledger.submit(job_id, identity)
    negative_rejections = [
        _expect_rejection(
            "request_identity_drift",
            lambda: drift_ledger.complete(job_id, drifted, result),
        ),
        _expect_rejection(
            "logical_block_drift",
            lambda: block_drift_ledger.complete(job_id, changed_blocks, result),
        ),
        _expect_rejection(
            "duplicate_completion",
            lambda: duplicate_ledger.complete(job_id, identity, result),
        ),
        _expect_rejection(
            "unknown_completion",
            lambda: _HandoffLedger().complete(job_id, identity, result),
        ),
        _expect_rejection(
            "failed_completion",
            lambda: failed_ledger.complete(
                job_id, identity, replace(result, success=False)
            ),
        ),
        _expect_rejection(
            "zero_size_completion",
            lambda: zero_size_ledger.complete(
                job_id, identity, replace(result, transfer_size=0)
            ),
        ),
    ]
    return {
        "evidence_kind": (
            "controlled_stub_pinned_worker_plus_separate_observer_ledger"
        ),
        "runtime_wiring_proven": False,
        "pinned_worker_preserved_fields": [
            "connector_job_id",
            "runtime_request_id",
            "source_spec",
            "destination_spec",
            "wait_set_job_ids",
        ],
        "observer_ledger_only_fields": [
            "trace_id",
            "engine_lifecycle_id",
            "recovery_epoch",
            "episode_id",
            "transfer_id",
            "logical_block_set",
        ],
        "profile_identity_propagation_proven": False,
        "job_id": job_id,
        "runtime_request_id": identity.runtime_request_id,
        "recovery_epoch": identity.recovery_epoch,
        "transfer_id": identity.transfer_id,
        "block_set_id": identity.block_set_id,
        "bytes_moved": result.transfer_size,
        "device_duration_ns": observed_durations[0],
        "wait_set": sorted(backend.wait_sets[0]),
        "observer_ledger_negative_rejections": negative_rejections,
    }


def validate_config_candidate_data(data: dict[str, Any]) -> dict[str, Any]:
    """Validate one source-compatible resolved config fixture.

    This does not approve communication evidence or a benchmark run.  A
    connector-free HBM control and a runtime-core tiering candidate are both
    accepted shapes; the latter remains formally blocked by issue-2 approval.
    """

    if data.get("schema") == (
        "request-lifecycle-profiler/benchmark-134-fixed-8gib-config-candidate/v1"
    ):
        canonical_bytes = json.dumps(
            data,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        _assert(
            hashlib.sha256(canonical_bytes).hexdigest()
            == BENCHMARK_134_INCOMPLETE_CANDIDATE_CANONICAL_SHA256,
            "benchmark-134 candidate semantic digest mismatch",
        )
        _assert(
            data.get("status") == "BLOCKED_INCOMPLETE_NOT_RUNNABLE_NOT_FROZEN",
            "benchmark-134 candidate must remain explicitly blocked",
        )
        pins = data.get("repository_pins")
        _assert(isinstance(pins, dict), "candidate repository_pins missing")
        runtime_pin = pins.get("runtime")
        device_pin = pins.get("device_plugin")
        _assert(isinstance(runtime_pin, dict), "candidate runtime pin missing")
        _assert(isinstance(device_pin, dict), "candidate device pin missing")
        _assert(
            runtime_pin.get("commit") == RUNTIME_COMMIT,
            "candidate runtime pin mismatch",
        )
        _assert(
            device_pin.get("commit") == DEVICE_COMMIT,
            "candidate device-plugin pin mismatch",
        )
        context = data.get("approved_context")
        _assert(isinstance(context, dict), "candidate approved_context missing")
        _assert(
            context.get("granted")
            == [
                "remaining_G0_configuration_candidate_work",
                "CPU_only_static_and_compatibility_checks",
            ],
            "candidate granted authority roster changed",
        )
        _assert(
            context.get("not_granted")
            == [
                "communication_mode_other_than_none",
                "G1_runtime_wiring",
                "runtime_or_device_source_edits",
                "NPU_admission_or_execution",
                "service_launch",
                "performance_experiment",
                "performance_claim",
            ],
            "candidate not_granted authority roster changed",
        )
        selected_family = context.get("selected_runtime_family")
        _assert(
            isinstance(selected_family, dict),
            "candidate selected_runtime_family missing",
        )
        _assert(
            selected_family
            == {
                "connector_name": "OffloadingConnector",
                "connector_class": (
                    "vllm.distributed.kv_transfer.kv_connector.v1."
                    "offloading_connector.OffloadingConnector"
                ),
                "spec_name": "TieringOffloadingSpec",
                "spec_class": ("vllm.v1.kv_offload.tiering.spec.TieringOffloadingSpec"),
                "connector_module_path_policy": ("OMIT_TO_USE_PINNED_RUNTIME_REGISTRY"),
                "spec_module_path_policy": "OMIT_TO_USE_PINNED_RUNTIME_REGISTRY",
                "ascend_worker_class": (
                    "vllm.v1.kv_offload.cpu.npu_worker.AscendCPUOffloadingWorker"
                ),
                "forbidden_device_spec_module": "vllm_ascend.kv_offload.npu",
                "recompute_scheduler_enable": False,
            },
            "candidate selected runtime family changed",
        )
        common = data.get("fixed_common_parameters")
        _assert(isinstance(common, dict), "candidate common parameters missing")
        capacity = common.get("device_kv_capacity")
        server = common.get("server_semantic_config")
        _assert(isinstance(capacity, dict), "candidate KV capacity missing")
        _assert(isinstance(server, dict), "candidate server config missing")
        _assert(
            capacity.get("bytes_per_device") == 8 * 1024**3
            and server.get("kv_cache_memory_bytes") == 8 * 1024**3,
            "candidate does not preserve exact 8-GiB device KV",
        )
        additional = server.get("additional_config")
        _assert(isinstance(additional, dict), "candidate scheduler guards missing")
        _assert(
            additional.get("recompute_scheduler_enable") is False
            and additional.get("SLO_limits_for_dynamic_batch") == -1,
            "candidate scheduler guards changed",
        )
        modes = data.get("mutually_exclusive_modes")
        _assert(isinstance(modes, list), "candidate modes missing")
        _assert(
            len(modes) == 3 and all(isinstance(mode, dict) for mode in modes),
            "candidate modes must be a closed three-object roster",
        )
        _assert(
            [mode.get("mode_id") for mode in modes]
            == [
                "hbm_only_no_connector",
                "tiering_disabled",
                "tiering_enabled",
            ],
            "candidate mode roster changed",
        )
        hbm_mode, disabled_mode, enabled_mode = modes
        _assert(
            hbm_mode.get("connector_present") is False
            and hbm_mode.get("known_kv_transfer_config") is None
            and hbm_mode.get("connector_or_spec_factory_must_not_be_called") is True
            and hbm_mode.get("runnable_mode_fragment") is None,
            "candidate HBM-only connector boundary changed",
        )
        hbm_communication = hbm_mode.get("communication")
        _assert(
            isinstance(hbm_communication, dict)
            and hbm_communication.get("communication_mode") == "none",
            "candidate HBM-only communication_mode must remain none",
        )
        disabled_profile = disabled_mode.get("profile_compatibility")
        disabled_resolution = disabled_mode.get("proposed_non_executable_resolution")
        disabled_communication = disabled_mode.get("communication")
        _assert(
            disabled_mode.get("connector_present") is None
            and isinstance(disabled_profile, dict)
            and disabled_profile.get("status")
            == "OUTSIDE_CURRENT_PROFILE_OWNER_IMPLEMENTATION_DECISION"
            and isinstance(disabled_resolution, dict)
            and disabled_resolution.get("connector_name") == "OffloadingConnector"
            and disabled_resolution.get("spec_name") == "CPUOffloadingSpec"
            and isinstance(disabled_communication, dict)
            and disabled_communication.get("communication_mode") is None
            and disabled_mode.get("runnable_mode_fragment") is None,
            "candidate tiering-disabled authority boundary changed",
        )
        enabled_resolution = enabled_mode.get("runtime_resolution")
        enabled_fragment = enabled_mode.get("known_kv_transfer_fragment")
        enabled_communication = enabled_mode.get("communication")
        _assert(
            enabled_mode.get("connector_present") is True
            and isinstance(enabled_resolution, dict)
            and enabled_resolution.get("connector_name") == "OffloadingConnector"
            and enabled_resolution.get("spec_name") == "TieringOffloadingSpec"
            and enabled_resolution.get("connector_module_path_policy") == "OMIT"
            and enabled_resolution.get("spec_module_path_policy") == "OMIT"
            and enabled_resolution.get("device_plugin_NPUTieringOffloadingSpec_allowed")
            is False
            and isinstance(enabled_fragment, dict)
            and enabled_fragment.get("kv_connector") == "OffloadingConnector"
            and isinstance(enabled_communication, dict)
            and enabled_communication.get("communication_mode") is None
            and enabled_communication.get("required_future_mode")
            == "issue2:kv-recovery-v1alpha1"
            and enabled_mode.get("runnable_mode_fragment") is None,
            "candidate tiering-enabled runtime family or gate changed",
        )
        runnability = data.get("runnability")
        _assert(isinstance(runnability, dict), "candidate runnability missing")
        _assert(
            all(
                runnability.get(field) is False
                for field in (
                    "is_fully_resolved",
                    "is_runnable",
                    "is_frozen_by_authority",
                    "server_argv_emitted",
                    "client_argvs_emitted",
                    "service_launch_authorized",
                    "NPU_execution_authorized",
                    "performance_experiment_authorized",
                )
            ),
            "incomplete candidate runnability or authorization gate changed",
        )
        gate_effects = data.get("gate_effects")
        _assert(isinstance(gate_effects, dict), "candidate gate_effects missing")
        _assert(
            all(
                gate_effects.get(field) is False
                for field in (
                    "G0_complete",
                    "G1_unblocked",
                    "communication_mode_non_none_unblocked",
                    "NPU_unblocked",
                    "service_launch_unblocked",
                    "performance_experiment_unblocked",
                    "performance_claim_unblocked",
                    "M0_proven",
                )
            ),
            "incomplete candidate formal gate effect changed",
        )
        blocked_decisions = data.get("blocked_decisions")
        _assert(
            isinstance(blocked_decisions, list)
            and all(isinstance(item, dict) for item in blocked_decisions)
            and [item.get("code") for item in blocked_decisions]
            == [
                "BLOCKED_COMMON_PARAMETER_AUTHORITY",
                "BLOCKED_CPU_BYTES_TO_USE",
                "BLOCKED_METRIC_COVERAGE",
                "BLOCKED_MODEL_REVISION",
                "BLOCKED_REQUEST_MANIFESTS",
                "BLOCKED_TIERING_DISABLED_SEMANTICS",
                "BLOCKED_COPY_OPTIMIZATION_TOGGLE",
                "BLOCKED_COMMUNICATION_MAPPING",
                "BLOCKED_P0_BASE_MODE_OVERLAY",
            ],
            "candidate blocked-decision roster changed",
        )
        return {
            "status": "BLOCKED_INCOMPLETE_CONFIGURATION_CANDIDATE_REVIEWED",
            "implementation_family": "mixed_three_mode_candidate",
            "formal_communication_admission": False,
        }

    _assert(data.get("runtime_commit") == RUNTIME_COMMIT, "runtime pin mismatch")
    _assert(
        data.get("device_plugin_commit") == DEVICE_COMMIT,
        "device-plugin pin mismatch",
    )
    resolved = data.get("resolved_config")
    _assert(isinstance(resolved, dict), "resolved_config must be an object")
    additional = resolved.get("additional_config")
    scheduler = resolved.get("scheduler_config")
    _assert(isinstance(additional, dict), "additional_config must be an object")
    _assert(isinstance(scheduler, dict), "scheduler_config must be an object")
    _assert(
        additional.get("recompute_scheduler_enable") is False,
        "recompute_scheduler_enable must be explicitly false",
    )
    _assert(
        additional.get("SLO_limits_for_dynamic_batch") == -1,
        "SLO_limits_for_dynamic_batch must be explicitly -1",
    )
    _assert(
        "scheduler_cls" in scheduler and scheduler["scheduler_cls"] is None,
        "scheduler_cls must be explicitly null/default runtime",
    )
    _assert(
        resolved.get("kv_cache_memory_bytes") == 8 * 1024**3,
        "kv_cache_memory_bytes must be exact 8 GiB",
    )

    transfer = resolved.get("kv_transfer_config")
    if transfer is None:
        family = "hbm_only_no_connector"
    else:
        _assert(isinstance(transfer, dict), "kv_transfer_config must be an object")
        _assert(
            transfer.get("kv_connector") == "OffloadingConnector",
            "selected connector must be runtime OffloadingConnector",
        )
        _assert(transfer.get("kv_role") == "kv_both", "kv_role must be kv_both")
        _assert(
            transfer.get("kv_connector_module_path") is None,
            "kv_connector_module_path must be null",
        )
        extra = transfer.get("kv_connector_extra_config")
        _assert(isinstance(extra, dict), "kv_connector_extra_config must be an object")
        _assert(
            extra.get("spec_name") == "TieringOffloadingSpec",
            "selected spec must be runtime TieringOffloadingSpec",
        )
        _assert(
            "spec_module_path" not in extra,
            "spec_module_path must be omitted to avoid the device NPU specs",
        )
        cpu_bytes_to_use = extra.get("cpu_bytes_to_use")
        _assert(
            isinstance(cpu_bytes_to_use, int)
            and not isinstance(cpu_bytes_to_use, bool)
            and cpu_bytes_to_use > 0,
            "cpu_bytes_to_use must be an explicit positive integer",
        )
        family = "runtime_core_offloading_connector"
    return {
        "status": "PASS_SOURCE_COMPATIBILITY_ONLY",
        "implementation_family": family,
        "formal_communication_admission": False,
    }


def validate_config_candidate(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        data = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProbeFailure(f"cannot read config candidate {path}: {exc}") from exc
    _assert(isinstance(data, dict), "config candidate root must be an object")
    if data.get("schema") == (
        "request-lifecycle-profiler/benchmark-134-fixed-8gib-config-candidate/v1"
    ):
        _assert(
            hashlib.sha256(raw).hexdigest()
            == BENCHMARK_134_INCOMPLETE_CANDIDATE_SHA256,
            "benchmark-134 candidate byte digest mismatch",
        )
    result = validate_config_candidate_data(data)
    return {"path": str(path.resolve()), **result}


def probe_real_import_environment(
    runtime_repository: GitBlobRepository, device_repository: GitBlobRepository
) -> dict[str, Any]:
    """Inspect import availability without importing vLLM or the NPU plugin."""

    origins: dict[str, str | None] = {}
    missing: list[str] = []
    for module_name in ("vllm", "vllm_ascend", "torch", "torch_npu"):
        try:
            spec = importlib.util.find_spec(module_name)
        except (ImportError, AttributeError, ValueError):
            spec = None
        origin = None if spec is None else spec.origin
        origins[module_name] = origin
        if spec is None:
            missing.append(module_name)

    reasons: list[str] = []
    if missing:
        reasons.append("missing_import_dependencies:" + ",".join(missing))

    for label, repository, module_name in (
        ("runtime", runtime_repository, "vllm"),
        ("device", device_repository, "vllm_ascend"),
    ):
        origin = origins[module_name]
        if origin is None:
            continue
        try:
            Path(origin).resolve().relative_to(repository.path.resolve())
        except ValueError:
            reasons.append(f"{label}_import_not_from_audited_sibling_repo")
            continue
        head = repository._run("rev-parse", "HEAD").stdout.decode().strip()
        if head != repository.commit:
            reasons.append(f"{label}_editable_head_is_{head}_not_{repository.commit}")

    if not reasons:
        reasons.append("real_pinned_import_not_executed_by_source_only_probe")
    return {
        "status": "BLOCKED",
        "reason_code": "REAL_PINNED_IMPORT_ENVIRONMENT_UNPROVEN",
        "reasons": reasons,
        "module_origins": origins,
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "note": (
            "AST and controlled-stub fakes do not prove a genuine pinned "
            "runtime/device "
            "import or startup"
        ),
    }


def _run_check(
    checks: list[dict[str, Any]], name: str, operation: Callable[[], dict[str, Any]]
) -> bool:
    try:
        details = operation()
    except (ProbeFailure, AssertionError, KeyError, TypeError, ValueError) as exc:
        checks.append({"name": name, "status": "FAIL", "error": str(exc)})
        return False
    checks.append({"name": name, "status": "PASS", "details": details})
    return True


def run_probe(
    runtime_repo: Path,
    device_repo: Path,
    config_paths: tuple[Path, ...] = (),
) -> dict[str, Any]:
    runtime_repository = GitBlobRepository(runtime_repo.resolve(), RUNTIME_COMMIT)
    device_repository = GitBlobRepository(device_repo.resolve(), DEVICE_COMMIT)
    checks: list[dict[str, Any]] = []

    runtime_sources: dict[str, str] = {}
    device_sources: dict[str, str] = {}

    def fingerprints() -> dict[str, Any]:
        nonlocal runtime_sources, device_sources
        runtime_sources = _load_and_fingerprint(runtime_repository, RUNTIME_BLOBS)
        device_sources = _load_and_fingerprint(device_repository, DEVICE_BLOBS)
        return {
            "runtime_commit": RUNTIME_COMMIT,
            "device_commit": DEVICE_COMMIT,
            "runtime_blob_count": len(runtime_sources),
            "device_blob_count": len(device_sources),
        }

    fingerprints_ok = _run_check(checks, "pinned_blob_fingerprints", fingerprints)
    source_ok = fingerprints_ok
    if fingerprints_ok:
        source_ok &= _run_check(
            checks,
            "scheduler_call_and_override_contract",
            lambda: verify_scheduler_contract(runtime_sources, device_sources),
        )
        source_ok &= _run_check(
            checks,
            "connector_spec_and_worker_factory_contract",
            lambda: verify_factory_contract(runtime_sources, device_sources),
        )
        source_ok &= _run_check(
            checks,
            "legacy_device_npu_negative_control",
            lambda: verify_legacy_npu_negative_control(
                runtime_repository, device_sources
            ),
        )
        source_ok &= _run_check(
            checks,
            "controlled_stub_worker_job_handoff_and_observer_ledger",
            lambda: verify_fake_handoff(
                runtime_sources[
                    "vllm/distributed/kv_transfer/kv_connector/v1/offloading/worker.py"
                ]
            ),
        )

    config_results: list[dict[str, Any]] = []
    config_ok = True
    for config_path in config_paths:
        try:
            config_results.append(validate_config_candidate(config_path))
        except ProbeFailure as exc:
            config_ok = False
            config_results.append(
                {"path": str(config_path), "status": "FAIL", "error": str(exc)}
            )

    real_import = probe_real_import_environment(runtime_repository, device_repository)
    failed = not source_ok or not config_ok
    overall_status = "FAILED" if failed else "BLOCKED"
    return {
        "schema": "rlp.g0-pinned-pair-probe/v1",
        "overall_status": overall_status,
        "evidence_status": "NOT_M0_PROVEN",
        "static_source_contract_status": (
            "FAILED" if not source_ok else "PASS_STATIC_ONLY"
        ),
        "real_pinned_import": real_import,
        "configuration_candidates": (
            config_results
            if config_paths
            else [{"status": "NOT_PROVIDED", "formal_admission": False}]
        ),
        "checks": checks,
        "gate_effects": {
            "runtime_source_edit_authorized": False,
            "communication_mode_non_none_authorized": False,
            "npu_authorized": False,
            "performance_experiment_authorized": False,
        },
    }


def _default_sibling(name: str) -> Path:
    repository_root = Path(__file__).resolve().parents[1]
    return repository_root.parent / name


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime-repo", type=Path, default=_default_sibling("vllm-hust")
    )
    parser.add_argument(
        "--device-repo", type=Path, default=_default_sibling("vllm-ascend-hust")
    )
    parser.add_argument(
        "--config",
        dest="config_paths",
        type=Path,
        action="append",
        default=[],
        help="repeatable path to one resolved G0 configuration candidate",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = run_probe(
        args.runtime_repo,
        args.device_repo,
        tuple(args.config_paths),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["overall_status"] == "FAILED":
        return EXIT_FAILED
    return EXIT_BLOCKED


if __name__ == "__main__":
    raise SystemExit(main())
