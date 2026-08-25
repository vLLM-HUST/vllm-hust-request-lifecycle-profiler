"""Run the preregistered Issue #19 observer-only M0 baseline on one NPU.

Each repetition owns one vLLM service lifecycle.  It runs the fixed 64-request
OASST1 group, exercises the six real request paths in their preregistered
order, records raw client/runtime evidence, and terminates the verified model
worker child last.  This runner never enables lifecycle reconciliation or changes
the scheduler/connector policy.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import http.client
import json
import math
import os
import signal
import socket
import statistics
import subprocess
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from vllm_request_lifecycle_profiler.issue19_m0 import (
    SCENARIO_TARGET_ORDINALS,
    SEEDS,
    TARGET_MODEL,
)
from vllm_request_lifecycle_profiler.oasst1_workload import (
    DEFAULT_DATA_CACHE,
    OASST1_FILENAME,
    build_oasst1_repetitions,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME = REPO_ROOT / "third_party" / "vllm-hust"
ASCEND = REPO_ROOT / "third_party" / "vllm-ascend-hust"
PYTHON = REPO_ROOT / ".venv-issue19" / "bin" / "python"
VLLM = REPO_ROOT / ".venv-issue19" / "bin" / "vllm"
MODEL_PATH = (
    Path.home()
    / ".cache/huggingface/hub/models--Qwen--Qwen2.5-14B-Instruct"
    / "snapshots/cf98f3b3bbb457ad9e2bb7baf9a0125b6b88caa8"
)
CONTROL_PREFIX = "/__issue19"
TERMINAL_EVENTS = frozenset({"generation_done", "aborted", "cancelled", "error"})
RECOVERY_STAGES = (
    "preempt",
    "restore_start",
    "restore_done",
    "scheduler_wakeup",
    "admission",
    "first_prefill_or_decode",
)
PRESSURE_PREFIX = (44, 1, 35, 0, 9, 4)
UNAFFECTED_ORDINALS = tuple(
    ordinal
    for ordinal in range(64)
    if ordinal not in set(SCENARIO_TARGET_ORDINALS.values())
)
MAX_TOKENS = 192
STAGGER_SECONDS = 0.2
CLIENT_TIMEOUT_SECONDS = 2.0
QUIESCENCE_STABLE_SECONDS = 5.0
QUIESCENCE_TIMEOUT_SECONDS = 120.0
SERVER_START_TIMEOUT_SECONDS = 240.0
SERVER_SHUTDOWN_TIMEOUT_SECONDS = 120.0


@dataclass(frozen=True)
class RequestResult:
    request_id: str
    internal_request_id: str
    ordinal: int
    role: str
    submitted_at_ns: int
    first_token_at_ns: int | None
    ended_at_ns: int
    http_status: int | None
    completion_tokens: int
    finish_reason: str | None
    saw_done: bool
    expected_fault_observed: bool
    error: str | None

    @property
    def latency_seconds(self) -> float:
        return (self.ended_at_ns - self.submitted_at_ns) / 1e9

    @property
    def ttft_seconds(self) -> float | None:
        if self.first_token_at_ns is None:
            return None
        return (self.first_token_at_ns - self.submitted_at_ns) / 1e9

    @property
    def tpot_seconds(self) -> float | None:
        if self.first_token_at_ns is None or self.completion_tokens < 2:
            return None
        return (self.ended_at_ns - self.first_token_at_ns) / (
            1e9 * (self.completion_tokens - 1)
        )


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _git_head(path: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _git_clean(path: Path) -> bool:
    return not subprocess.run(
        ["git", "-C", str(path), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _npu_snapshot() -> str:
    return subprocess.run(
        ["npu-smi", "info"], check=True, capture_output=True, text=True
    ).stdout


def _npu_idle(snapshot: str, device: int) -> bool:
    return f"No running processes found in NPU {device}" in snapshot


def _json_request(
    port: int,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    timeout: float = 5.0,
) -> tuple[int, dict[str, Any]]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        encoded = None if body is None else json.dumps(body).encode()
        headers = {} if encoded is None else {"Content-Type": "application/json"}
        connection.request(method, path, body=encoded, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        value = json.loads(raw) if raw else {}
        return response.status, value if isinstance(value, dict) else {"value": value}
    finally:
        connection.close()


def _wait_for_health(process: subprocess.Popen[bytes], port: int) -> None:
    deadline = time.monotonic() + SERVER_START_TIMEOUT_SECONDS
    last_error = "service_not_ready"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"service exited during startup: {process.returncode}")
        try:
            status, _ = _json_request(port, "GET", "/health", timeout=2.0)
            if status == 200:
                return
            last_error = f"health_status_{status}"
        except Exception as exc:  # noqa: BLE001 - readiness retry is bounded.
            last_error = f"{type(exc).__name__}: {exc}"
        time.sleep(1.0)
    raise TimeoutError(f"service health timeout: {last_error}")


def _control_state(port: int) -> dict[str, Any]:
    status, value = _json_request(port, "GET", f"{CONTROL_PREFIX}/state")
    if status != 200:
        raise RuntimeError(f"control state failed with HTTP {status}: {value}")
    return value


def _active_ids(state: dict[str, Any]) -> set[str]:
    engine = state.get("engine", {})
    observer = state.get("observer", {})
    return {
        *map(str, engine.get("active_internal_request_ids", [])),
        *map(str, observer.get("active_request_ids", [])),
    }


def _wait_until_active(
    port: int, internal_request_id: str, timeout: float = 30.0
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if internal_request_id in _active_ids(_control_state(port)):
            return
        time.sleep(0.05)
    raise TimeoutError(f"request never became active: {internal_request_id}")


def _wait_for_quiescence(port: int) -> tuple[bool, dict[str, Any], float]:
    started = time.monotonic()
    deadline = started + QUIESCENCE_TIMEOUT_SECONDS
    stable_since: float | None = None
    last_state: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last_state = _control_state(port)
        if not _active_ids(last_state):
            stable_since = stable_since or time.monotonic()
            if time.monotonic() - stable_since >= QUIESCENCE_STABLE_SECONDS:
                return True, last_state, time.monotonic() - started
        else:
            stable_since = None
        time.sleep(0.25)
    return False, last_state, time.monotonic() - started


def _request_body(workload_request: Any) -> dict[str, Any]:
    return {
        "model": TARGET_MODEL,
        "messages": workload_request.openai_messages(),
        "max_tokens": MAX_TOKENS,
        "temperature": 0.0,
        "stream": True,
        "stream_options": {"include_usage": True},
    }


def _set_socket_timeout(connection: http.client.HTTPConnection, value: float) -> None:
    if connection.sock is not None:
        connection.sock.settimeout(max(0.001, value))


def _read_stream(
    connection: http.client.HTTPConnection,
    response: http.client.HTTPResponse,
    *,
    submitted_at_ns: int,
    deadline: float | None = None,
    disconnect_after_first: bool = False,
) -> tuple[int, str | None, int | None, bool, bool, str | None]:
    completion_tokens = 0
    finish_reason: str | None = None
    first_token_at_ns: int | None = None
    saw_done = False
    disconnected = False
    stream_error: str | None = None
    while True:
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("client deadline reached")
            _set_socket_timeout(connection, remaining)
        raw = response.readline()
        if not raw:
            break
        if not raw.startswith(b"data:"):
            continue
        data = raw[5:].strip()
        if data == b"[DONE]":
            saw_done = True
            break
        if not data:
            continue
        payload = json.loads(data)
        if "error" in payload:
            stream_error = json.dumps(
                payload["error"], ensure_ascii=False, sort_keys=True
            )
        choices = payload.get("choices", [])
        if choices:
            choice = choices[0]
            delta = choice.get("delta", {})
            content = delta.get("content") if isinstance(delta, dict) else None
            if isinstance(content, str) and content:
                completion_tokens += 1
                first_token_at_ns = first_token_at_ns or time.monotonic_ns()
                if disconnect_after_first:
                    disconnected = True
                    response.close()
                    connection.close()
                    break
            finish_reason = choice.get("finish_reason") or finish_reason
        usage = payload.get("usage")
        if isinstance(usage, dict) and isinstance(usage.get("completion_tokens"), int):
            completion_tokens = usage["completion_tokens"]
    return (
        completion_tokens,
        finish_reason,
        first_token_at_ns,
        saw_done,
        disconnected,
        stream_error,
    )


def _role_for_ordinal(ordinal: int, *, normal_control: bool = False) -> str:
    if normal_control:
        return (
            "unaffected_survivor"
            if ordinal in UNAFFECTED_ORDINALS
            else "normal_control"
        )
    for role, target in SCENARIO_TARGET_ORDINALS.items():
        if ordinal == target:
            return role
    return "unaffected_survivor"


def _run_request(
    port: int,
    workload_request: Any,
    *,
    delay_seconds: float,
    normal_control: bool = False,
) -> RequestResult:
    time.sleep(delay_seconds)
    role = _role_for_ordinal(
        workload_request.ordinal, normal_control=normal_control
    )
    external_id = workload_request.request_id
    internal_id = f"chatcmpl-{external_id}"
    submitted_at_ns = time.monotonic_ns()
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=300.0)
    status: int | None = None
    completion_tokens = 0
    finish_reason: str | None = None
    first_token_at_ns: int | None = None
    saw_done = False
    expected_fault_observed = False
    error: str | None = None
    try:
        connection.request(
            "POST",
            "/v1/chat/completions",
            body=json.dumps(_request_body(workload_request)).encode(),
            headers={"Content-Type": "application/json", "X-Request-Id": external_id},
        )
        response = connection.getresponse()
        status = response.status
        if status != 200:
            error = response.read().decode(errors="replace")
        elif role == "client_disconnect":
            (
                completion_tokens,
                finish_reason,
                first_token_at_ns,
                saw_done,
                expected_fault_observed,
                stream_error,
            ) = _read_stream(
                connection,
                response,
                submitted_at_ns=submitted_at_ns,
                disconnect_after_first=True,
            )
            error = stream_error
        elif role == "client_timeout":
            try:
                (
                    completion_tokens,
                    finish_reason,
                    first_token_at_ns,
                    saw_done,
                    _,
                    stream_error,
                ) = _read_stream(
                    connection,
                    response,
                    submitted_at_ns=submitted_at_ns,
                    deadline=submitted_at_ns / 1e9 + CLIENT_TIMEOUT_SECONDS,
                )
                error = stream_error
            except TimeoutError:
                expected_fault_observed = True
                response.close()
                connection.close()
        elif role == "duplicate_cancel":
            _wait_until_active(port, internal_id)
            control_status, control = _json_request(
                port,
                "POST",
                f"{CONTROL_PREFIX}/duplicate-abort",
                {"internal_request_id": internal_id, "attempts": 2},
            )
            expected_fault_observed = (
                control_status == 200
                and control.get("internal_request_id") == internal_id
                and control.get("attempts") == 2
            )
            (
                completion_tokens,
                finish_reason,
                first_token_at_ns,
                saw_done,
                _,
                stream_error,
            ) = _read_stream(connection, response, submitted_at_ns=submitted_at_ns)
            error = stream_error
        else:
            (
                completion_tokens,
                finish_reason,
                first_token_at_ns,
                saw_done,
                _,
                stream_error,
            ) = _read_stream(connection, response, submitted_at_ns=submitted_at_ns)
            error = stream_error
            if role == "worker_exit":
                expected_fault_observed = stream_error is not None or not saw_done
    except Exception as exc:  # noqa: BLE001 - raw client failure is evidence.
        if role in {
            "client_disconnect",
            "client_timeout",
            "duplicate_cancel",
            "worker_exit",
        }:
            expected_fault_observed = expected_fault_observed or isinstance(
                exc, (ConnectionError, GeneratorExit, TimeoutError, socket.timeout)
            )
        error = f"{type(exc).__name__}: {exc}"
    finally:
        with contextlib.suppress(Exception):
            connection.close()
    return RequestResult(
        request_id=external_id,
        internal_request_id=internal_id,
        ordinal=workload_request.ordinal,
        role=role,
        submitted_at_ns=submitted_at_ns,
        first_token_at_ns=first_token_at_ns,
        ended_at_ns=time.monotonic_ns(),
        http_status=status,
        completion_tokens=completion_tokens,
        finish_reason=finish_reason,
        saw_done=saw_done,
        expected_fault_observed=expected_fault_observed,
        error=error,
    )


def _arrival_order() -> tuple[int, ...]:
    remainder = tuple(
        ordinal
        for ordinal in range(64)
        if ordinal not in {*PRESSURE_PREFIX, SCENARIO_TARGET_ORDINALS["worker_exit"]}
    )
    order = (*PRESSURE_PREFIX, *remainder)
    if len(order) != 63 or len(set(order)) != 63:
        raise AssertionError("arrival order must cover exactly 63 unique requests")
    return order


def _run_initial_group(
    port: int,
    repetition: tuple[Any, ...],
    *,
    normal_control: bool = False,
) -> list[RequestResult]:
    order = _arrival_order()
    results: list[RequestResult] = []
    with ThreadPoolExecutor(max_workers=len(order)) as executor:
        futures: dict[Future[RequestResult], int] = {
            executor.submit(
                _run_request,
                port,
                repetition[ordinal],
                delay_seconds=position * STAGGER_SECONDS,
                normal_control=normal_control,
            ): ordinal
            for position, ordinal in enumerate(order)
        }
        for future in as_completed(futures):
            results.append(future.result())
    return sorted(results, key=lambda item: item.ordinal)


def _process_table() -> list[dict[str, Any]]:
    output = subprocess.run(
        ["ps", "-eo", "pid=,ppid=,comm=,args="],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    rows = []
    for line in output.splitlines():
        fields = line.strip().split(maxsplit=3)
        if len(fields) == 4:
            rows.append(
                {
                    "pid": int(fields[0]),
                    "ppid": int(fields[1]),
                    "comm": fields[2],
                    "args": fields[3],
                }
            )
    return rows


def _owned_worker_process(
    api_pid: int, rows: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Select the one real MultiprocExecutor worker owned by this API server.

    TP=1 normally uses UniProcExecutor, where the model worker is embedded in
    EngineCore and cannot fail independently.  The Issue #19 service therefore
    explicitly uses the ``mp`` backend and this selector refuses to substitute
    EngineCore itself for a worker process.
    """

    rows = _process_table() if rows is None else rows
    children: dict[int, list[int]] = {}
    by_pid = {row["pid"]: row for row in rows}
    for row in rows:
        children.setdefault(row["ppid"], []).append(row["pid"])
    descendants: set[int] = set()
    pending = list(children.get(api_pid, []))
    while pending:
        pid = pending.pop()
        if pid in descendants:
            continue
        descendants.add(pid)
        pending.extend(children.get(pid, []))
    engine_candidates = [
        by_pid[pid]
        for pid in descendants
        if pid in by_pid
        and ("EngineCore" in by_pid[pid]["comm"] or "EngineCore" in by_pid[pid]["args"])
    ]
    if len(engine_candidates) != 1:
        raise RuntimeError(
            f"expected one owned EngineCore descendant, found {engine_candidates}"
        )
    engine = engine_candidates[0]
    worker_descendants: set[int] = set()
    pending = list(children.get(engine["pid"], []))
    while pending:
        pid = pending.pop()
        if pid in worker_descendants:
            continue
        worker_descendants.add(pid)
        pending.extend(children.get(pid, []))
    candidates = [
        by_pid[pid]
        for pid in worker_descendants
        if pid in by_pid
        and (
            by_pid[pid]["comm"].startswith("VLLM::Worker")
            or "VLLM::Worker" in by_pid[pid]["args"]
        )
    ]
    if len(candidates) != 1:
        raise RuntimeError(
            "expected one owned MultiprocExecutor worker below EngineCore; "
            f"refusing EngineCore substitution, found {candidates}"
        )
    return {**candidates[0], "engine_pid": engine["pid"]}


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=30)


def _graceful_stop_service(process: subprocess.Popen[bytes]) -> None:
    """Ask the API owner to drain EngineCore/Worker before any group fallback."""

    if process.poll() is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        process.terminate()
    try:
        process.wait(timeout=SERVER_SHUTDOWN_TIMEOUT_SECONDS + 30)
    except subprocess.TimeoutExpired:
        _terminate_process_group(process)


def _server_command(port: int) -> list[str]:
    kv_config = {
        "kv_connector": "OffloadingConnector",
        "kv_role": "kv_both",
        "kv_connector_extra_config": {
            "spec_name": "TieringOffloadingSpec",
            "cpu_bytes_to_use": 8 * 1024**3,
            "secondary_tiers": [],
        },
    }
    additional = {
        "kv_recovery_profile_enabled": True,
        "recompute_scheduler_enable": False,
        "SLO_limits_for_dynamic_batch": -1,
    }
    return [
        str(VLLM),
        "serve",
        str(MODEL_PATH),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--served-model-name",
        TARGET_MODEL,
        "--dtype",
        "bfloat16",
        "--max-model-len",
        "10880",
        "--enforce-eager",
        "--trust-remote-code",
        "--enable-request-id-headers",
        "--gpu-memory-utilization",
        "0.6",
        "--distributed-executor-backend",
        "mp",
        "--kv-cache-memory-bytes",
        str(2 * 1024**3),
        "--kv-transfer-config",
        json.dumps(kv_config, separators=(",", ":")),
        "--additional-config",
        json.dumps(additional, separators=(",", ":")),
        "--shutdown-timeout",
        "120",
        "--middleware",
        "vllm_request_lifecycle_profiler.issue19_control.issue19_control_middleware",
    ]


def _server_environment(run_dir: Path, device: int, run_id: str) -> dict[str, str]:
    # Child processes change initialization context; never hand them a
    # repository-relative evidence or fault-injection path.
    run_dir = run_dir.resolve()
    environment = os.environ.copy()
    inherited_pythonpath = environment.get("PYTHONPATH", "").strip()
    python_paths = [str(RUNTIME), str(ASCEND), str(REPO_ROOT / "src")]
    if inherited_pythonpath:
        python_paths.append(inherited_pythonpath)
    environment.update(
        {
            "ASCEND_RT_VISIBLE_DEVICES": str(device),
            # Keep CANN's acl/tbe site-packages while placing pinned sources first.
            "PYTHONPATH": os.pathsep.join(python_paths),
            "VLLM_PLUGINS": "ascend,request_lifecycle_profiler",
            "VLLM_VERSION": "0.23.0",
            "VLLM_DISABLE_REQUEST_ID_RANDOMIZATION": "1",
            "VLLM_RLP_TRACE_EXPORT_PATH": str(run_dir / "trace"),
            "VLLM_RLP_COMMUNICATION_MODE": "issue2:kv-recovery-v1alpha1",
            "VLLM_RLP_KV_RECOVERY_RUN_ID": run_id,
            "VLLM_RLP_PROFILER_PARENT_COMMIT": _git_head(REPO_ROOT),
            "VLLM_RLP_RUNTIME_CORE_COMMIT": _git_head(RUNTIME),
            "VLLM_RLP_DEVICE_PLUGIN_COMMIT": _git_head(ASCEND),
            "VLLM_RLP_WORKER_FAILURE_SENTINEL_DIR": str(run_dir / "worker_failure"),
        }
    )
    return environment


def _read_jsonl_files(run_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(run_dir.glob("trace*.jsonl")):
        with path.open() as source:
            for line_number, line in enumerate(source, start=1):
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSONL at {path}:{line_number}") from exc
                if not isinstance(value, dict):
                    raise TypeError(f"non-object JSONL at {path}:{line_number}")
                value["_source"] = path.name
                records.append(value)
    return records


def _unclosed_observer_shards(records: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Return every process/profile shard that started but did not summarize."""

    pairs = (
        ("process_start", "process_summary", "trace"),
        ("profile_start", "profile_summary", "profile"),
    )
    unclosed: list[dict[str, str]] = []
    for start_type, summary_type, stream in pairs:
        starts = {
            (str(row.get("_source", "")), str(row.get("process_uuid", "")))
            for row in records
            if row.get("record_type") == start_type
        }
        summaries = {
            (str(row.get("_source", "")), str(row.get("process_uuid", "")))
            for row in records
            if row.get("record_type") == summary_type
        }
        for source, process_uuid in sorted(starts - summaries):
            unclosed.append(
                {
                    "stream": stream,
                    "source": source,
                    "process_uuid": process_uuid,
                }
            )
    return unclosed


def _offload_mmap_paths() -> set[str]:
    return {str(path) for path in Path("/dev/shm").glob("vllm_offload_*.mmap")}


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _externally_closed_worker_shards(
    records: list[dict[str, Any]],
    unclosed_shards: list[dict[str, str]],
    worker_pid: int | None,
) -> list[dict[str, str]]:
    """Accept only the killed Worker's exact trace/profile shard pair."""

    if not isinstance(worker_pid, int):
        return []
    worker_uuids = {
        str(row.get("process_uuid"))
        for row in records
        if row.get("record_type") in {"process_start", "profile_start"}
        and row.get("pid") == worker_pid
        and isinstance(row.get("process_uuid"), str)
    }
    if len(worker_uuids) != 1 or len(unclosed_shards) != 2:
        return []
    process_uuid = next(iter(worker_uuids))
    if {(row["stream"], row["process_uuid"]) for row in unclosed_shards} != {
        ("trace", process_uuid),
        ("profile", process_uuid),
    }:
        return []
    return list(unclosed_shards)


def _trace_id(run_id: str, internal_request_id: str) -> str:
    return hashlib.sha256(
        f"{run_id}\0{internal_request_id}".encode("ascii")
    ).hexdigest()[:32]


def _terminal_chain_valid(events: list[dict[str, Any]]) -> bool:
    """Validate one logical terminal chain across API and EngineCore shards."""

    if not events:
        return False
    sources = [str(event.get("_source", "")) for event in events]
    if not all(sources) or len(sources) != len(set(sources)):
        return False
    ordered = sorted(events, key=lambda event: int(event["timestamp_ns"]))
    causes = [str(event.get("metadata", {}).get("terminal_cause")) for event in ordered]
    names = [str(event.get("event_name")) for event in ordered]
    if len(ordered) == 1:
        return causes[0] in {
            "complete",
            "client_disconnect",
            "client_timeout",
            "explicit_cancel",
            "engine_failure",
            "error",
        }
    if len(ordered) != 2:
        return False
    if names == ["error", "error"] and causes == [
        "engine_failure",
        "engine_failure",
    ]:
        # EngineCore owns the worker-generation failure; API subsequently
        # reports the same causal terminal to the client.
        return True
    # The API owns the client-visible terminal and EngineCore subsequently
    # observes its internal abort. These are two observations of one causal
    # chain, not two logical request terminals.
    return (
        names[1] == "aborted"
        and causes[1] == "explicit_cancel"
        and causes[0] in {"client_disconnect", "client_timeout", "explicit_cancel"}
    )


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _distribution(results: list[RequestResult]) -> dict[str, Any]:
    completed = [
        result
        for result in results
        if result.role in {"normal_completion", "recovery", "unaffected_survivor"}
        and result.http_status == 200
        and result.saw_done
    ]

    def summarize(values: list[float]) -> dict[str, float | None]:
        return {
            "p50": _percentile(values, 0.50),
            "p95": _percentile(values, 0.95),
            "p99": _percentile(values, 0.99),
        }

    survivors = [result for result in completed if result.role == "unaffected_survivor"]
    return {
        "latency_seconds": summarize([result.latency_seconds for result in completed]),
        "ttft_seconds": summarize(
            [
                value
                for result in completed
                if (value := result.ttft_seconds) is not None
            ]
        ),
        "tpot_seconds": summarize(
            [
                value
                for result in completed
                if (value := result.tpot_seconds) is not None
            ]
        ),
        "unaffected_survivor_p99_seconds": _percentile(
            [result.latency_seconds for result in survivors], 0.99
        ),
        "completed_request_count": len(completed),
        "unaffected_survivor_count": len(survivors),
    }


def _complete_recovery(profile: list[dict[str, Any]], runtime_id: str) -> bool:
    episodes: dict[str, list[dict[str, Any]]] = {}
    for record in profile:
        if (
            record.get("record_type") == "recovery_event"
            and record.get("runtime_request_id") == runtime_id
            and isinstance(record.get("episode_id"), str)
        ):
            episodes.setdefault(record["episode_id"], []).append(record)
    for records in episodes.values():
        ordered = sorted(records, key=lambda record: int(record["timestamp_ns"]))
        stages = [str(record.get("stage")) for record in ordered]
        indexes = [stages.index(stage) for stage in RECOVERY_STAGES if stage in stages]
        if len(indexes) == len(RECOVERY_STAGES) and indexes == sorted(indexes):
            return True
    return False


_RESOURCE_TRANSITIONS = {
    "resource_acquired": "acquire",
    "resource_transfer_pending": "transfer_pending",
    "resource_released": "release",
    "resource_policy_retained": "policy_retain",
    "resource_invalidated": "invalidate",
}


def _resource_ledger(
    base: list[dict[str, Any]],
    profile: list[dict[str, Any]],
    worker_generation: str | None,
    worker_monitor_events: list[dict[str, Any]],
    pending_witness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the request-scoped ownership ledger from persisted runtime events."""

    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    malformed: list[dict[str, Any]] = []
    for row in base:
        transition = _RESOURCE_TRANSITIONS.get(str(row.get("event_name")))
        if transition is None:
            continue
        metadata = row.get("metadata", {})
        values = (
            metadata.get("resource_type"),
            metadata.get("resource_id"),
            metadata.get("worker_generation"),
            metadata.get("runtime_request_id"),
        )
        resource_units = metadata.get("resource_units")
        if not all(isinstance(value, str) and value for value in values) or not (
            isinstance(resource_units, int)
            and not isinstance(resource_units, bool)
            and resource_units >= 1
        ):
            malformed.append({"event_id": row.get("event_id"), "reason": "identity"})
            continue
        if metadata.get("resource_transition") != transition:
            malformed.append(
                {"event_id": row.get("event_id"), "reason": "transition_mismatch"}
            )
            continue
        key = (str(values[0]), str(values[1]), str(values[2]))
        grouped.setdefault(key, []).append(row)

    # SIGKILL can race the asynchronous trace writer. The failure injector's
    # fsync-backed witness is written only after backend submission and profiler
    # admission, so it is the crash-safe ownership source for that exact job.
    if pending_witness:
        witnessed_values = (
            pending_witness.get("transfer_id"),
            pending_witness.get("runtime_request_id"),
            pending_witness.get("worker_generation"),
            pending_witness.get("timestamp_ns"),
        )
        if all(
            isinstance(value, str) and value for value in witnessed_values[:3]
        ) and isinstance(witnessed_values[3], int):
            transfer_id, request_id, generation, timestamp_ns = witnessed_values
            key = ("offload_transfer", transfer_id, generation)
            witnessed_rows = [
                {
                    "event_name": "resource_acquired",
                    "timestamp_ns": timestamp_ns,
                    "metadata": {
                        "runtime_request_id": request_id,
                        "resource_type": "offload_transfer",
                        "resource_id": transfer_id,
                        "resource_transition": "acquire",
                        "resource_units": 1,
                        "worker_generation": generation,
                    },
                    "_source": "pending_transfer_witness",
                },
                {
                    "event_name": "resource_transfer_pending",
                    "timestamp_ns": timestamp_ns,
                    "metadata": {
                        "runtime_request_id": request_id,
                        "resource_type": "offload_transfer",
                        "resource_id": transfer_id,
                        "resource_transition": "transfer_pending",
                        "resource_units": 1,
                        "worker_generation": generation,
                    },
                    "_source": "pending_transfer_witness",
                },
            ]
            existing = grouped.setdefault(key, [])
            # The asynchronous trace can contain either prefix of this pair.
            # Rebuild the exact admitted pair from the fsync-backed witness so
            # a persisted ``pending`` without its preceding ``acquire`` cannot
            # be reordered into false invalid evidence. Preserve only later
            # closure observations from the trace shard.
            existing[:] = [
                row
                for row in existing
                if row.get("metadata", {}).get("resource_transition")
                not in {"acquire", "transfer_pending"}
            ]
            existing[:0] = witnessed_rows

    profile_transfers = {
        str(row["transfer_id"]): row
        for row in profile
        if row.get("record_type") == "transfer_event"
        and row.get("transfer_phase") == "submit"
        and isinstance(row.get("transfer_id"), str)
    }
    if pending_witness and isinstance(pending_witness.get("transfer_id"), str):
        profile_transfers.setdefault(
            pending_witness["transfer_id"],
            {"_source": "pending_transfer_witness"},
        )
    resource_transfer_ids = {
        resource_id
        for resource_type, resource_id, _generation in grouped
        if resource_type == "offload_transfer"
    }
    errors = list(malformed)
    missing_resource_types = sorted(
        {"kv_capacity_lease", "offload_transfer"}
        - {resource_type for resource_type, _, _ in grouped}
    )
    if missing_resource_types:
        errors.append(
            {"reason": "missing_resource_types", "types": missing_resource_types}
        )
    if set(profile_transfers) != resource_transfer_ids:
        errors.append(
            {
                "reason": "transfer_profile_ledger_mismatch",
                "profile_only": sorted(set(profile_transfers) - resource_transfer_ids),
                "ledger_only": sorted(resource_transfer_ids - set(profile_transfers)),
            }
        )

    generation_exit_ns = None
    if worker_generation is not None and len(worker_monitor_events) == 1:
        generation_exit_ns = worker_monitor_events[0].get("timestamp_ns")
    resources: list[dict[str, Any]] = []
    orphan_resources: list[dict[str, Any]] = []
    externally_invalidated: list[dict[str, Any]] = []
    for (resource_type, resource_id, generation), rows in sorted(grouped.items()):
        ordered = sorted(rows, key=lambda row: int(row["timestamp_ns"]))
        transitions = [
            str(row.get("metadata", {}).get("resource_transition")) for row in ordered
        ]
        request_ids = {
            str(row.get("metadata", {}).get("runtime_request_id")) for row in ordered
        }
        resource_units = [
            int(row.get("metadata", {}).get("resource_units", 0)) for row in ordered
        ]
        expected = (
            {
                ("acquire", "release"),
                ("acquire", "policy_retain"),
                ("acquire", "invalidate"),
            }
            if resource_type == "kv_capacity_lease"
            else {
                ("acquire", "transfer_pending", "release"),
                ("acquire", "transfer_pending", "invalidate"),
            }
            if resource_type == "offload_transfer"
            else set()
        )
        externally_closed = (
            resource_type == "offload_transfer"
            and tuple(transitions) == ("acquire", "transfer_pending")
            and generation == worker_generation
            and isinstance(generation_exit_ns, int)
            and int(ordered[-1]["timestamp_ns"]) < generation_exit_ns
        )
        valid_sequence = len(request_ids) == 1 and (
            tuple(transitions) in expected or externally_closed
        )
        resource = {
            "resource_type": resource_type,
            "resource_id": resource_id,
            "worker_generation": generation,
            "runtime_request_ids": sorted(request_ids),
            "transitions": transitions,
            "resource_units": resource_units,
            "max_resource_units": max(resource_units, default=0),
            "externally_invalidated": externally_closed,
        }
        resources.append(resource)
        if externally_closed:
            externally_invalidated.append(resource)
        elif not valid_sequence:
            profile_row = profile_transfers.get(resource_id)
            profile_done = any(
                row.get("record_type") == "transfer_event"
                and row.get("transfer_id") == resource_id
                and row.get("transfer_phase") == "done"
                for row in profile
            )
            if profile_row is not None and profile_done:
                errors.append({"reason": "missing_release_observation", **resource})
            elif tuple(transitions) in {
                ("acquire",),
                ("acquire", "transfer_pending"),
            }:
                orphan_resources.append(resource)
            else:
                errors.append({"reason": "invalid_resource_sequence", **resource})

    return {
        "resource_event_count": sum(len(rows) for rows in grouped.values()),
        "resource_count": len(grouped),
        "resources": resources,
        "errors": errors,
        "complete": not errors and bool(resources),
        "orphan_resources": orphan_resources,
        "orphan_resource_units": sum(
            row["max_resource_units"] for row in orphan_resources
        ),
        "externally_invalidated_resources": externally_invalidated,
    }


def _analyze(
    run_dir: Path,
    run_id: str,
    results: list[RequestResult],
    quiescent: bool,
    quiescence_state: dict[str, Any],
    worker_signal_ns: int,
    worker_event: dict[str, Any],
    leaked_offload_mmaps: list[str],
    target_pid_alive_after_shutdown: bool,
    engine_pid_alive_after_shutdown: bool,
    server_returncode: int | None,
) -> dict[str, Any]:
    records = _read_jsonl_files(run_dir)
    base = [record for record in records if record.get("schema_version")]
    profile = [record for record in records if record.get("schema")]
    summaries = [
        record
        for record in records
        if record.get("record_type") in {"process_summary", "profile_summary"}
    ]
    loss_records = [
        record
        for record in records
        if record.get("record_type") in {"loss_interval", "profile_loss_interval"}
    ]
    incomplete_files = sorted(path.name for path in run_dir.glob("trace*.incomplete*"))
    unclosed_shards = _unclosed_observer_shards(records)
    target = worker_event.get("target", {})
    worker_pid = target.get("pid") if isinstance(target, dict) else None
    externally_closed_shards = _externally_closed_worker_shards(
        records, unclosed_shards, worker_pid
    )
    summary_clean = bool(summaries) and all(
        record.get("close_outcome") == "drained"
        and record.get("dropped_data_count") == 0
        and record.get("writer_failure_count") == 0
        for record in summaries
    )

    terminal_counts: dict[str, int] = {}
    terminal_names: dict[str, list[str]] = {}
    terminal_chain_validity: dict[str, bool] = {}
    for result in results:
        trace_id = _trace_id(run_id, result.internal_request_id)
        events = [
            record
            for record in base
            if record.get("record_type") == "event"
            and record.get("trace_id") == trace_id
            and record.get("event_name") in TERMINAL_EVENTS
        ]
        terminal_counts[result.request_id] = len(events)
        terminal_names[result.request_id] = [
            str(record["event_name"]) for record in events
        ]
        terminal_chain_validity[result.request_id] = _terminal_chain_valid(events)

    transfers: dict[str, list[dict[str, Any]]] = {}
    for record in profile:
        transfer_id = record.get("transfer_id")
        if record.get("record_type") == "transfer_event" and isinstance(
            transfer_id, str
        ):
            transfers.setdefault(transfer_id, []).append(record)
    unmatched = []
    for transfer_id, rows in transfers.items():
        submits = [row for row in rows if row.get("transfer_phase") == "submit"]
        dones = [row for row in rows if row.get("transfer_phase") == "done"]
        if len(submits) != 1 or len(dones) != 1:
            row = submits[0] if submits else rows[0]
            unmatched.append(
                {
                    "transfer_id": transfer_id,
                    "runtime_request_id": row.get("runtime_request_id"),
                    "process_uuid": row.get("process_uuid"),
                    "submit_count": len(submits),
                    "done_count": len(dones),
                    "submitted_before_worker_exit": bool(
                        submits
                        and submits[0].get("timestamp_ns", worker_signal_ns + 1)
                        < worker_signal_ns
                    ),
                }
            )

    by_role = {
        result.role: result
        for result in results
        if result.role != "unaffected_survivor"
    }
    unaffected = [result for result in results if result.role == "unaffected_survivor"]
    successful_roles = {"normal_completion", "recovery", "unaffected_survivor"}
    client_correct = all(
        (
            result.http_status == 200
            and result.saw_done
            and result.error is None
            and result.completion_tokens > 0
        )
        if result.role in successful_roles
        else result.expected_fault_observed
        for result in results
    )
    exact_terminal = all(terminal_chain_validity.values())
    duplicate = by_role.get("duplicate_cancel")
    observer = quiescence_state.get("observer", {})
    duplicate_attempts = (
        observer.get("abort_attempts", {}).get(duplicate.internal_request_id, 0)
        if duplicate is not None
        else 0
    )
    active_at_quiescence = sorted(_active_ids(quiescence_state))
    recovery_complete_request_ids = sorted(
        result.internal_request_id
        for result in results
        if _complete_recovery(profile, result.internal_request_id)
    )
    # The contract requires the real event set to cover recovery; it does not
    # require the scheduler to preempt one preselected request identity. Keep
    # the fixed request/order unchanged and accept only an actually completed
    # six-stage recovery chain from that lifecycle.
    recovery_complete = bool(recovery_complete_request_ids)
    worker = by_role.get("worker_exit")
    worker_generation = (
        f"VllmWorker-0:{worker_pid}" if isinstance(worker_pid, int) else None
    )
    worker_monitor_events = [
        row
        for row in base
        if row.get("record_type") == "event"
        and row.get("metadata", {}).get("terminal_cause") == "engine_failure"
        and row.get("metadata", {}).get("worker_generation") == worker_generation
    ]
    worker_request_events = [
        row
        for row in base
        if worker is not None
        and row.get("record_type") == "event"
        and row.get("trace_id") == _trace_id(run_id, worker.internal_request_id)
        and row.get("metadata", {}).get("terminal_cause") == "engine_failure"
    ]
    pending_witness = worker_event.get("pending_transfer_witness", {})
    worker_failure_witnessed = (
        worker_event.get("injection") == "pending-transfer-sigkill"
        and worker_event.get("ownership_verified") is True
        and worker_event.get("signal") == "SIGKILL"
        and pending_witness.get("pid") == worker_pid
        and pending_witness.get("worker_generation") == worker_generation
        and isinstance(pending_witness.get("transfer_id"), str)
        and isinstance(pending_witness.get("timestamp_ns"), int)
        and pending_witness["timestamp_ns"] < worker_signal_ns
        and target_pid_alive_after_shutdown is False
        and engine_pid_alive_after_shutdown is False
        and server_returncode == 0
        and len(worker_monitor_events) == 1
        and len(worker_request_events) == 1
    )
    resource_ledger = _resource_ledger(
        base,
        profile,
        worker_generation,
        worker_monitor_events,
        pending_witness,
    )
    transfer_record_structure_valid = all(
        row["submit_count"] == 1 and row["done_count"] in {0, 1} for row in unmatched
    )
    observer_complete = (
        summary_clean
        and not loss_records
        and not incomplete_files
        and unclosed_shards == externally_closed_shards
        and transfer_record_structure_valid
    )
    pre_worker_zombies = active_at_quiescence if not quiescent else []
    worker_zombies = (
        [worker.internal_request_id]
        if worker is not None
        and (
            not worker_request_events
            or target_pid_alive_after_shutdown
            or engine_pid_alive_after_shutdown
        )
        else []
    )
    zombie_request_ids = sorted({*pre_worker_zombies, *worker_zombies})
    zombie_request_count = len(zombie_request_ids)
    orphan_lease_count = len(resource_ledger["orphan_resources"]) + len(
        leaked_offload_mmaps
    )
    pathology = zombie_request_count > 0 or orphan_lease_count > 0
    evidence_valid = all(
        (
            client_correct,
            exact_terminal,
            duplicate_attempts == 2,
            recovery_complete,
            worker_failure_witnessed,
            observer_complete,
            resource_ledger["complete"],
        )
    )
    state_conservation = zombie_request_count == 0 and orphan_lease_count == 0
    correctness = evidence_valid and state_conservation
    server_log = (run_dir / "server.log").read_text(errors="replace")
    resource_tracker_warning_count = server_log.count(
        "resource_tracker: There appear to be"
    )
    return {
        "evidence_class": "real-online",
        "metadata": {"data_source": "real-online-oasst1-fixed-projection"},
        "request_count": len(results),
        "unaffected_request_count": len(unaffected),
        "client_correct": client_correct,
        "exact_terminal": exact_terminal,
        "terminal_counts": terminal_counts,
        "terminal_names": terminal_names,
        "terminal_chain_validity": terminal_chain_validity,
        "duplicate_abort_attempts": duplicate_attempts,
        "recovery_complete": recovery_complete,
        "recovery_complete_request_ids": recovery_complete_request_ids,
        "worker_failure_witnessed": worker_failure_witnessed,
        "worker_monitor_event_count": len(worker_monitor_events),
        "worker_request_failure_event_count": len(worker_request_events),
        "observer_complete": observer_complete,
        "summary_count": len(summaries),
        "loss_record_count": len(loss_records),
        "incomplete_trace_files": incomplete_files,
        "unclosed_observer_shards": unclosed_shards,
        "externally_closed_worker_shards": externally_closed_shards,
        "leaked_offload_mmaps": leaked_offload_mmaps,
        "target_pid_alive_after_shutdown": target_pid_alive_after_shutdown,
        "engine_pid_alive_after_shutdown": engine_pid_alive_after_shutdown,
        "server_returncode": server_returncode,
        "resource_tracker_warning_count": resource_tracker_warning_count,
        "active_at_quiescence": active_at_quiescence,
        "zombie_request_ids": zombie_request_ids,
        "zombie_request_count": zombie_request_count,
        "transfer_count": len(transfers),
        "unmatched_transfers": unmatched,
        "worker_generation_invalidated_transfer_ids": [
            row["resource_id"]
            for row in resource_ledger["externally_invalidated_resources"]
            if row["resource_type"] == "offload_transfer"
        ],
        "resource_ledger": resource_ledger,
        "orphan_lease_count": orphan_lease_count,
        "orphan_resource_units": resource_ledger["orphan_resource_units"],
        "evidence_valid": evidence_valid,
        "state_conservation": state_conservation,
        "correctness": correctness,
        "pathology_observed": pathology,
        "latency_pathology_evaluable": False,
        "latency_pathology_observed": None,
        "latency_pathology_reason": "no preregistered paired normal boundary",
        "distribution": _distribution(results),
        "lifecycle_boundary_p99_seconds": _lifecycle_boundary_p99(
            base, results, run_id
        ),
    }


def _lifecycle_boundary_p99(
    base: list[dict[str, Any]],
    results: list[RequestResult],
    run_id: str,
) -> dict[str, dict[str, float | int | None]]:
    """Summarize predeclared non-fatal lifecycle boundaries for survivors."""

    boundary_values: dict[str, list[float]] = {
        "queue_to_schedule": [],
        "schedule_to_prefill_done": [],
        "prefill_to_decode_done": [],
        "preempt_to_resume": [],
        "terminal_to_last_release": [],
    }
    for result in results:
        if result.ordinal not in UNAFFECTED_ORDINALS:
            continue
        trace_id = _trace_id(run_id, result.internal_request_id)
        events = [
            row
            for row in base
            if row.get("record_type") == "event"
            and row.get("trace_id") == trace_id
            and isinstance(row.get("timestamp_ns"), int)
        ]
        by_name: dict[str, list[int]] = {}
        for row in events:
            by_name.setdefault(str(row.get("event_name")), []).append(
                int(row["timestamp_ns"])
            )

        def add_boundary(
            name: str,
            starts: tuple[str, ...],
            ends: tuple[str, ...],
            observations: dict[str, list[int]] = by_name,
        ) -> None:
            start_values = [
                value for key in starts for value in observations.get(key, [])
            ]
            end_values = [
                value for key in ends for value in observations.get(key, [])
            ]
            if not start_values or not end_values:
                return
            start = min(start_values)
            end = max(end_values)
            if end >= start:
                boundary_values[name].append((end - start) / 1e9)

        add_boundary("queue_to_schedule", ("queued",), ("scheduled",))
        add_boundary("schedule_to_prefill_done", ("scheduled",), ("prefill_done",))
        add_boundary("prefill_to_decode_done", ("prefill_started",), ("decode_done",))
        add_boundary("preempt_to_resume", ("preempted",), ("resumed",))
        add_boundary(
            "terminal_to_last_release",
            tuple(TERMINAL_EVENTS),
            ("resource_released", "resource_invalidated"),
        )
    return {
        name: {"count": len(values), "p99": _percentile(values, 0.99)}
        for name, values in boundary_values.items()
    }


def _normal_control_analysis(
    run_dir: Path,
    run_id: str,
    results: list[RequestResult],
    *,
    quiescent: bool,
    leaked_offload_mmaps: list[str],
    worker_pid_alive_after_shutdown: bool,
    engine_pid_alive_after_shutdown: bool,
    server_returncode: int | None,
) -> dict[str, Any]:
    records = _read_jsonl_files(run_dir)
    base = [record for record in records if record.get("schema_version")]
    profile = [record for record in records if record.get("schema")]
    summaries = [
        record
        for record in records
        if record.get("record_type") in {"process_summary", "profile_summary"}
    ]
    loss_records = [
        record
        for record in records
        if record.get("record_type") in {"loss_interval", "profile_loss_interval"}
    ]
    incomplete_files = sorted(path.name for path in run_dir.glob("trace*.incomplete*"))
    unclosed_shards = _unclosed_observer_shards(records)
    summary_clean = bool(summaries) and all(
        record.get("close_outcome") == "drained"
        and record.get("dropped_data_count") == 0
        and record.get("writer_failure_count") == 0
        for record in summaries
    )
    terminal_chain_validity: dict[str, bool] = {}
    for result in results:
        trace_id = _trace_id(run_id, result.internal_request_id)
        terminal_events = [
            record
            for record in base
            if record.get("record_type") == "event"
            and record.get("trace_id") == trace_id
            and record.get("event_name") in TERMINAL_EVENTS
        ]
        terminal_chain_validity[result.request_id] = (
            len(terminal_events) == 1
            and terminal_events[0].get("event_name") == "generation_done"
            and terminal_events[0].get("metadata", {}).get("terminal_cause")
            == "complete"
        )
    client_correct = all(
        result.http_status == 200
        and result.saw_done
        and result.error is None
        and result.completion_tokens > 0
        for result in results
    )
    resource_ledger = _resource_ledger(base, profile, None, [])
    observer_complete = (
        summary_clean
        and not loss_records
        and not incomplete_files
        and not unclosed_shards
    )
    evidence_valid = all(
        (
            len(results) == 64,
            client_correct,
            all(terminal_chain_validity.values()),
            quiescent,
            observer_complete,
            resource_ledger["complete"],
            not resource_ledger["orphan_resources"],
            not leaked_offload_mmaps,
            not worker_pid_alive_after_shutdown,
            not engine_pid_alive_after_shutdown,
            server_returncode == 0,
        )
    )
    return {
        "arm": "normal-control",
        "evidence_valid": evidence_valid,
        "client_correct": client_correct,
        "exact_terminal": all(terminal_chain_validity.values()),
        "terminal_chain_validity": terminal_chain_validity,
        "observer_complete": observer_complete,
        "summary_count": len(summaries),
        "loss_record_count": len(loss_records),
        "incomplete_trace_files": incomplete_files,
        "unclosed_observer_shards": unclosed_shards,
        "resource_ledger": resource_ledger,
        "leaked_offload_mmaps": leaked_offload_mmaps,
        "worker_pid_alive_after_shutdown": worker_pid_alive_after_shutdown,
        "engine_pid_alive_after_shutdown": engine_pid_alive_after_shutdown,
        "server_returncode": server_returncode,
        "distribution": _distribution(results),
        "lifecycle_boundary_p99_seconds": _lifecycle_boundary_p99(
            base, results, run_id
        ),
    }


def _paired_latency(
    fault: dict[str, Any], normal_control: dict[str, Any]
) -> dict[str, Any]:
    fault_p99 = fault["distribution"]["unaffected_survivor_p99_seconds"]
    control_p99 = normal_control["distribution"]["unaffected_survivor_p99_seconds"]
    comparable = (
        fault.get("evidence_valid") is True
        and normal_control.get("evidence_valid") is True
        and isinstance(fault_p99, (int, float))
        and isinstance(control_p99, (int, float))
        and control_p99 > 0
        and fault["distribution"].get("unaffected_survivor_count")
        == len(UNAFFECTED_ORDINALS)
        and normal_control["distribution"].get("unaffected_survivor_count")
        == len(UNAFFECTED_ORDINALS)
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
        control_row = normal_control["lifecycle_boundary_p99_seconds"].get(name, {})
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


def _run_directory(
    output_root: Path, repetition_index: int, seed: int, arm: str
) -> Path:
    if arm not in {"fault", "normal-control"}:
        raise ValueError(f"unsupported arm: {arm}")
    return (output_root / f"r{repetition_index:02d}-{seed}-{arm}").resolve()


def _run_one(
    repetition_index: int,
    repetition: tuple[Any, ...],
    *,
    device: int,
    port: int,
    output_root: Path,
) -> dict[str, Any]:
    seed = SEEDS[repetition_index]
    run_dir = _run_directory(output_root, repetition_index, seed, "fault")
    if run_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing run: {run_dir}")
    run_dir.mkdir(parents=True)
    (run_dir / "worker_failure").mkdir()
    before = _npu_snapshot()
    offload_mmaps_before = _offload_mmap_paths()
    (run_dir / "npu_before.txt").write_text(before)
    if not _npu_idle(before, device):
        raise RuntimeError(f"NPU {device} is not idle before repetition")

    run_id = uuid.uuid4().hex
    command = _server_command(port)
    environment = _server_environment(run_dir, device, run_id)
    manifest = {
        "schema_version": "issue19-m0-runtime-manifest/v1",
        "evidence_class": "real-online",
        "metadata": {"data_source": "real-online-oasst1-fixed-projection"},
        "repetition": repetition_index,
        "seed": seed,
        "run_id": run_id,
        "device": device,
        "port": port,
        "arm": "fault",
        "observer_only": True,
        "lifecycle_reconcile": False,
        "arrival_order": list(_arrival_order()),
        "request_ids": [request.request_id for request in repetition],
        "scenario_targets": {
            role: repetition[ordinal].request_id
            for role, ordinal in SCENARIO_TARGET_ORDINALS.items()
        },
        "stagger_ms": int(STAGGER_SECONDS * 1000),
        "worker_exit_is_final_action": True,
        "command": command,
        "commits": {
            "profiler": _git_head(REPO_ROOT),
            "runtime": _git_head(RUNTIME),
            "ascend": _git_head(ASCEND),
        },
        "target": {
            "model": TARGET_MODEL,
            "model_path": str(MODEL_PATH),
            "dtype": "bfloat16",
            "tensor_parallel_size": 1,
            "distributed_executor_backend": "mp",
            "max_model_len": 10880,
            "kv_cache_memory_bytes": 2 * 1024**3,
            "connector": "OffloadingConnector",
            "offloading_spec": "TieringOffloadingSpec",
            "cpu_offload_bytes": 8 * 1024**3,
        },
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(run_dir / "manifest.json", manifest)

    log_handle = (run_dir / "server.log").open("wb")
    process = subprocess.Popen(
        command,
        cwd=REPO_ROOT,
        env=environment,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    results: list[RequestResult] = []
    worker_event: dict[str, Any] = {}
    quiescent = False
    quiescence_state: dict[str, Any] = {}
    quiescence_seconds = 0.0
    worker_signal_ns = 0
    target_pid_alive_after_shutdown = True
    engine_pid_alive_after_shutdown = True
    try:
        _wait_for_health(process, port)
        (run_dir / "npu_during.txt").write_text(_npu_snapshot())
        results = _run_initial_group(port, repetition)
        quiescent, quiescence_state, quiescence_seconds = _wait_for_quiescence(port)
        _write_json(run_dir / "pre_worker_quiescence.json", quiescence_state)

        worker_request = repetition[SCENARIO_TARGET_ORDINALS["worker_exit"]]
        with ThreadPoolExecutor(max_workers=1) as executor:
            worker_future = executor.submit(
                _run_request, port, worker_request, delay_seconds=0.0
            )
            internal_id = f"chatcmpl-{worker_request.request_id}"
            _wait_until_active(port, internal_id)
            owned = _owned_worker_process(process.pid)
            sentinel_dir = Path(environment["VLLM_RLP_WORKER_FAILURE_SENTINEL_DIR"])
            arm_path = sentinel_dir / f"{owned['pid']}.pending-transfer-arm"
            witness_path = sentinel_dir / f"{owned['pid']}.pending-transfer.json"
            arm_path.touch(exist_ok=False)
            witness_deadline = time.monotonic() + QUIESCENCE_TIMEOUT_SECONDS
            while (
                not witness_path.is_file()
                and not worker_future.done()
                and time.monotonic() < witness_deadline
            ):
                time.sleep(0.01)
            if not witness_path.is_file():
                raise RuntimeError(
                    "worker request completed without a witnessed pending transfer"
                )
            pending_witness = json.loads(witness_path.read_text())
            if pending_witness.get("pid") != owned["pid"]:
                raise RuntimeError("pending-transfer witness PID mismatch")
            failure_state = _control_state(port)
            _write_json(run_dir / "at_worker_failure_state.json", failure_state)
            worker_signal_ns = time.monotonic_ns()
            os.kill(owned["pid"], signal.SIGKILL)
            worker_event = {
                "injection": "pending-transfer-sigkill",
                "injection_timestamp_ns": worker_signal_ns,
                "api_pid": process.pid,
                "target": owned,
                "ownership_verified": True,
                "signal": "SIGKILL",
                "arm_path": str(arm_path.relative_to(run_dir)),
                "witness_path": str(witness_path.relative_to(run_dir)),
                "pending_transfer_witness": pending_witness,
                "request_id": worker_request.request_id,
                "internal_request_id": internal_id,
            }
            _write_json(run_dir / "worker_exit.json", worker_event)
            results.append(
                worker_future.result(timeout=SERVER_SHUTDOWN_TIMEOUT_SECONDS)
            )

        try:
            process.wait(timeout=SERVER_SHUTDOWN_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("service did not stop after owned worker exit") from exc
        target_pid_alive_after_shutdown = _pid_exists(int(owned["pid"]))
        engine_pid_alive_after_shutdown = _pid_exists(int(owned["engine_pid"]))
    finally:
        _graceful_stop_service(process)
        log_handle.close()
        (run_dir / "npu_after.txt").write_text(_npu_snapshot())
    leaked_offload_mmaps = sorted(_offload_mmap_paths() - offload_mmaps_before)
    _write_json(
        run_dir / "post_worker_resource_state.json",
        {
            "target_pid_alive": target_pid_alive_after_shutdown,
            "engine_pid_alive": engine_pid_alive_after_shutdown,
            "leaked_offload_mmaps": leaked_offload_mmaps,
        },
    )

    results.sort(key=lambda item: item.ordinal)
    _write_json(
        run_dir / "client_results.json",
        {
            "schema_version": "issue19-m0-client-results/v1",
            "results": [
                {
                    **asdict(result),
                    "latency_seconds": result.latency_seconds,
                    "ttft_seconds": result.ttft_seconds,
                    "tpot_seconds": result.tpot_seconds,
                }
                for result in results
            ],
        },
    )
    analysis = _analyze(
        run_dir,
        run_id,
        results,
        quiescent,
        quiescence_state,
        worker_signal_ns,
        worker_event,
        leaked_offload_mmaps,
        target_pid_alive_after_shutdown,
        engine_pid_alive_after_shutdown,
        process.returncode,
    )
    analysis.update(
        {
            "repetition": repetition_index,
            "seed": seed,
            "run_id": run_id,
            "quiescent_before_worker_exit": quiescent,
            "quiescence_seconds": quiescence_seconds,
            "worker_exit": worker_event,
            "server_returncode": process.returncode,
        }
    )
    _write_json(run_dir / "analysis.json", analysis)
    return analysis


def _run_normal_control(
    repetition_index: int,
    repetition: tuple[Any, ...],
    *,
    device: int,
    port: int,
    output_root: Path,
) -> dict[str, Any]:
    seed = SEEDS[repetition_index]
    run_dir = _run_directory(output_root, repetition_index, seed, "normal-control")
    if run_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing run: {run_dir}")
    run_dir.mkdir(parents=True)
    (run_dir / "worker_failure").mkdir()
    before = _npu_snapshot()
    offload_mmaps_before = _offload_mmap_paths()
    (run_dir / "npu_before.txt").write_text(before)
    if not _npu_idle(before, device):
        raise RuntimeError(f"NPU {device} is not idle before repetition")

    run_id = uuid.uuid4().hex
    command = _server_command(port)
    environment = _server_environment(run_dir, device, run_id)
    manifest = {
        "schema_version": "issue19-m0-runtime-manifest/v1",
        "evidence_class": "real-online",
        "metadata": {"data_source": "real-online-oasst1-fixed-projection"},
        "repetition": repetition_index,
        "seed": seed,
        "run_id": run_id,
        "device": device,
        "port": port,
        "arm": "normal-control",
        "observer_only": True,
        "lifecycle_reconcile": False,
        "arrival_order": list(_arrival_order()),
        "final_request_ordinal": SCENARIO_TARGET_ORDINALS["worker_exit"],
        "request_ids": [request.request_id for request in repetition],
        "normal_completion_ordinals": list(range(64)),
        "unaffected_survivor_ordinals": list(UNAFFECTED_ORDINALS),
        "disabled_faults": [
            "client_disconnect",
            "client_timeout",
            "duplicate_cancel",
            "worker_sigkill",
        ],
        "stagger_ms": int(STAGGER_SECONDS * 1000),
        "command": command,
        "commits": {
            "profiler": _git_head(REPO_ROOT),
            "runtime": _git_head(RUNTIME),
            "ascend": _git_head(ASCEND),
        },
        "target": {
            "model": TARGET_MODEL,
            "model_path": str(MODEL_PATH),
            "dtype": "bfloat16",
            "tensor_parallel_size": 1,
            "distributed_executor_backend": "mp",
            "max_model_len": 10880,
            "kv_cache_memory_bytes": 2 * 1024**3,
            "connector": "OffloadingConnector",
            "offloading_spec": "TieringOffloadingSpec",
            "cpu_offload_bytes": 8 * 1024**3,
        },
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(run_dir / "manifest.json", manifest)

    log_handle = (run_dir / "server.log").open("wb")
    process = subprocess.Popen(
        command,
        cwd=REPO_ROOT,
        env=environment,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    results: list[RequestResult] = []
    quiescent = False
    worker_pid = -1
    engine_pid = -1
    try:
        _wait_for_health(process, port)
        owned = _owned_worker_process(process.pid)
        worker_pid = int(owned["pid"])
        engine_pid = int(owned["engine_pid"])
        (run_dir / "npu_during.txt").write_text(_npu_snapshot())
        results = _run_initial_group(port, repetition, normal_control=True)
        quiescent, state, _ = _wait_for_quiescence(port)
        _write_json(run_dir / "pre_final_quiescence.json", state)
        final_request = repetition[SCENARIO_TARGET_ORDINALS["worker_exit"]]
        results.append(
            _run_request(
                port,
                final_request,
                delay_seconds=0.0,
                normal_control=True,
            )
        )
        quiescent_after_final, state, _ = _wait_for_quiescence(port)
        quiescent = quiescent and quiescent_after_final
        _write_json(run_dir / "post_final_quiescence.json", state)
    finally:
        _graceful_stop_service(process)
        log_handle.close()
        (run_dir / "npu_after.txt").write_text(_npu_snapshot())
    worker_pid_alive = worker_pid > 0 and _pid_exists(worker_pid)
    engine_pid_alive = engine_pid > 0 and _pid_exists(engine_pid)
    leaked_offload_mmaps = sorted(_offload_mmap_paths() - offload_mmaps_before)
    _write_json(
        run_dir / "post_service_resource_state.json",
        {
            "worker_pid": worker_pid,
            "engine_pid": engine_pid,
            "worker_pid_alive": worker_pid_alive,
            "engine_pid_alive": engine_pid_alive,
            "leaked_offload_mmaps": leaked_offload_mmaps,
        },
    )
    results.sort(key=lambda item: item.ordinal)
    _write_json(
        run_dir / "client_results.json",
        {
            "schema_version": "issue19-m0-client-results/v1",
            "results": [
                {
                    **asdict(result),
                    "latency_seconds": result.latency_seconds,
                    "ttft_seconds": result.ttft_seconds,
                    "tpot_seconds": result.tpot_seconds,
                }
                for result in results
            ],
        },
    )
    analysis = _normal_control_analysis(
        run_dir,
        run_id,
        results,
        quiescent=quiescent,
        leaked_offload_mmaps=leaked_offload_mmaps,
        worker_pid_alive_after_shutdown=worker_pid_alive,
        engine_pid_alive_after_shutdown=engine_pid_alive,
        server_returncode=process.returncode,
    )
    analysis.update({"repetition": repetition_index, "seed": seed, "run_id": run_id})
    _write_json(run_dir / "analysis.json", analysis)
    return analysis


def _aggregate(output_root: Path, results: list[dict[str, Any]]) -> dict[str, Any]:
    arm_evidence_valid = all(result.get("evidence_valid", False) for result in results)
    correctness = all(result["correctness"] for result in results)
    resource_violation_count = sum(
        bool(result["pathology_observed"]) for result in results
    )
    latency_gate_evaluable = bool(results) and all(
        result.get("latency_pathology_evaluable", False) for result in results
    )
    evidence_valid = arm_evidence_valid and latency_gate_evaluable
    latency_violation_count = (
        sum(bool(result["latency_pathology_observed"]) for result in results)
        if latency_gate_evaluable
        else None
    )
    latency_boundary_counts: dict[str, int] = {}
    if latency_gate_evaluable:
        for result in results:
            if not result.get("latency_pathology_observed"):
                continue
            boundary = result.get("latency_top1_boundary")
            if isinstance(boundary, str):
                latency_boundary_counts[boundary] = (
                    latency_boundary_counts.get(boundary, 0) + 1
                )
    dominant_latency_boundary = (
        max(latency_boundary_counts, key=latency_boundary_counts.get)
        if latency_boundary_counts
        else None
    )
    dominant_latency_boundary_count = (
        latency_boundary_counts[dominant_latency_boundary]
        if dominant_latency_boundary is not None
        else 0
    )
    p99_values = [
        value
        for result in results
        if (value := result["distribution"]["unaffected_survivor_p99_seconds"])
        is not None
    ]
    complete = len(results) == 10
    go = (
        complete
        and evidence_valid
        and (
            resource_violation_count >= 8
            or dominant_latency_boundary_count >= 8
        )
    )
    decision = (
        "INCOMPLETE"
        if not complete
        else "INVALID_EVIDENCE"
        if not evidence_valid
        else "GO"
        if go
        else "NO_GO"
    )
    aggregate = {
        "schema_version": "issue19-m0-baseline-summary/v2",
        "evidence_class": "real-online",
        "metadata": {"data_source": "real-online-oasst1-fixed-projection"},
        "completed_repetitions": len(results),
        "evidence_valid_100_percent": evidence_valid,
        "correctness_100_percent": correctness,
        "resource_pathology_repetition_count": resource_violation_count,
        "latency_pathology_evaluable": latency_gate_evaluable,
        "latency_pathology_repetition_count": latency_violation_count,
        "latency_top1_boundary_counts": latency_boundary_counts,
        "dominant_latency_top1_boundary": dominant_latency_boundary,
        "dominant_latency_top1_boundary_count": dominant_latency_boundary_count,
        "pathology_repetition_count": max(
            resource_violation_count, dominant_latency_boundary_count
        ),
        "required_pathology_repetition_count": 8,
        "go_for_treatment": go,
        "decision": decision,
        "unaffected_survivor_p99_seconds": {
            "all": p99_values,
            "median": statistics.median(p99_values) if p99_values else None,
            "iqr": (
                statistics.quantiles(p99_values, n=4)[2]
                - statistics.quantiles(p99_values, n=4)[0]
                if len(p99_values) >= 4
                else None
            ),
        },
        "repetitions": results,
    }
    _write_json(output_root / "summary.json", aggregate)
    return aggregate


def _parse_repetitions(value: str) -> tuple[int, ...]:
    indexes = tuple(int(item) for item in value.split(","))
    if not indexes or len(set(indexes)) != len(indexes):
        raise argparse.ArgumentTypeError("repetitions must be unique")
    if any(index < 0 or index >= 10 for index in indexes):
        raise argparse.ArgumentTypeError("repetitions must be in [0, 9]")
    return indexes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", type=int, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--repetitions", type=_parse_repetitions, default=tuple(range(10))
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.device <= 7:
        parser.error("device must be in [0, 7]")
    if not 1 <= args.port <= 65535:
        parser.error("port must be in [1, 65535]")
    if not all(
        (
            _git_clean(REPO_ROOT),
            _git_clean(RUNTIME),
            _git_clean(ASCEND),
            PYTHON.is_file(),
            VLLM.is_file(),
            MODEL_PATH.is_dir(),
        )
    ):
        raise RuntimeError("repository, environment, or model preflight failed")
    repetitions = build_oasst1_repetitions(DEFAULT_DATA_CACHE / OASST1_FILENAME)
    plan = {
        "schema_version": "issue19-m0-fixed-execution/v2",
        "evidence_class": "real-online",
        "metadata": {"data_source": "real-online-oasst1-fixed-projection"},
        "device": args.device,
        "port": args.port,
        "repetitions": list(args.repetitions),
        "seeds": list(SEEDS),
        "requests_per_lifecycle": 64,
        "arrival_order": list(_arrival_order()),
        "arrival_stagger_ms": int(STAGGER_SECONDS * 1000),
        "concurrency": 63,
        "client_timeout_seconds": CLIENT_TIMEOUT_SECONDS,
        "quiescence_stable_seconds": QUIESCENCE_STABLE_SECONDS,
        "quiescence_timeout_seconds": QUIESCENCE_TIMEOUT_SECONDS,
        "worker_exit_is_final_action": True,
        "lifecycle_reconcile": False,
        "pathology_gate": {"required_repetitions": 8, "total_repetitions": 10},
        "stop_on_evidence_invalid": True,
        "oracle_semantics": {
            "evidence_valid": (
                "client/event/injection/ownership evidence is complete enough to "
                "judge the baseline"
            ),
            "state_conservation": "zero zombie requests and zero orphan leases",
            "baseline_pathology": (
                "state-conservation failure is measured pathology, not missing evidence"
            ),
        },
        "latency_gate": {
            "threshold_relative_p99": 0.10,
            "required_repetitions": 8,
            "status": "matched-normal-control-per-seed",
            "unaffected_request_ordinals": list(UNAFFECTED_ORDINALS),
            "top1_requirement": "same non-fatal lifecycle boundary in at least 8/10",
        },
        "scenario_semantics": {
            "normal_completion": "complete through the real OpenAI route",
            "client_disconnect": "close the streaming HTTP connection after first data",
            "client_timeout": "close at the fixed 2.0 second client deadline",
            "duplicate_cancel": "call the same real AsyncLLM internal identity twice",
            "recovery": "observe naturally triggered preemption and H2D recovery",
            "worker_exit": (
                "arm the one verified MultiprocExecutor Worker child last, require "
                "a durable real pending-transfer witness, then SIGKILL that exact "
                "Worker; never substitute EngineCore"
            ),
        },
        "lifecycles": [
            {
                "repetition": index,
                "seed": SEEDS[index],
                "arm_order": (
                    ["normal-control", "fault"]
                    if index % 2 == 0
                    else ["fault", "normal-control"]
                ),
                "request_ids": [request.request_id for request in repetitions[index]],
                "scenario_targets": {
                    role: repetitions[index][ordinal].request_id
                    for role, ordinal in SCENARIO_TARGET_ORDINALS.items()
                },
            }
            for index in range(10)
        ],
    }
    if args.dry_run:
        print(json.dumps(plan, indent=2, sort_keys=True))
        return
    args.output_dir.mkdir(parents=True, exist_ok=False)
    _write_json(args.output_dir / "fixed_plan.json", plan)
    results: list[dict[str, Any]] = []
    for index in args.repetitions:
        arm_order = (
            ("normal-control", "fault")
            if index % 2 == 0
            else ("fault", "normal-control")
        )
        arm_results: dict[str, dict[str, Any]] = {}
        for arm in arm_order:
            arm_results[arm] = (
                _run_normal_control(
                    index,
                    repetitions[index],
                    device=args.device,
                    port=args.port,
                    output_root=args.output_dir,
                )
                if arm == "normal-control"
                else _run_one(
                    index,
                    repetitions[index],
                    device=args.device,
                    port=args.port,
                    output_root=args.output_dir,
                )
            )
        fault = arm_results["fault"]
        normal_control = arm_results["normal-control"]
        latency = _paired_latency(fault, normal_control)
        result = {
            **fault,
            "arm_order": list(arm_order),
            "normal_control": normal_control,
            "paired_latency": latency,
            "evidence_valid": (
                fault.get("evidence_valid") is True
                and normal_control.get("evidence_valid") is True
                and latency.get("evaluable") is True
            ),
            "latency_pathology_evaluable": latency.get("evaluable") is True,
            "latency_pathology_observed": latency.get("observed"),
            "latency_pathology_reason": latency.get("reason"),
            "latency_top1_boundary": latency.get("top1_boundary"),
        }
        results.append(result)
        _aggregate(args.output_dir, results)
        print(
            json.dumps(
                {
                    "repetition": index,
                    "evidence_valid": result["evidence_valid"],
                    "correctness": result["correctness"],
                    "pathology_observed": result["pathology_observed"],
                },
                sort_keys=True,
            ),
            flush=True,
        )
        if not result["evidence_valid"]:
            break
    summary = _aggregate(args.output_dir, results)
    print(json.dumps({"status": summary["decision"], **plan}, sort_keys=True))


if __name__ == "__main__":
    main()
