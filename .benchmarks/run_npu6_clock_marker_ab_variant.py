#!/usr/bin/env python3
"""Run one profiler-matched NPU6 marker overhead variant."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path("/usr/local/python3.12.13/bin/python3")
DEFAULT_MODEL = Path("/workspace/models/Qwen2.5-7B-Instruct")
SERVED_MODEL = "clock-ab-qwen"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one marker-disabled or marker-enabled NPU6 serving variant."
    )
    parser.add_argument(
        "--mode", choices=("marker-disabled", "marker-enabled"), required=True
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--case-id", default="shared_scenario_structured_agent_decode")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--warmup-requests", type=int, default=4)
    parser.add_argument("--repeat-count", type=int, default=12)
    parser.add_argument("--max-requests", type=int, default=4)
    parser.add_argument("--request-max-tokens", type=int, default=32)
    parser.add_argument("--measured-concurrency", type=int, default=16)
    parser.add_argument("--offered-rate-rps", type=float, default=2.0)
    parser.add_argument("--measured-duration-s", type=float, default=24.0)
    parser.add_argument(
        "--profiler-task-time",
        choices=("l0", "l1", "l2", "on"),
        default="l1",
        help="Provenance for the enclosing msprof --task-time option.",
    )
    parser.add_argument("--server-timeout-s", type=float, default=180.0)
    return parser.parse_args()


def _git_revision(path: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=path, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _wait_for_health(
    endpoint: str, process: subprocess.Popen[bytes], timeout_s: float
) -> None:
    opener = build_opener(ProxyHandler({}))
    deadline = time.monotonic() + timeout_s
    last_error = "not attempted"
    while time.monotonic() < deadline:
        return_code = process.poll()
        if return_code is not None:
            raise RuntimeError(f"vLLM server exited before health check: {return_code}")
        try:
            with opener.open(endpoint + "/health", timeout=2.0) as response:
                if response.status == 200:
                    return
        except Exception as error:  # noqa: BLE001 - retained for provenance.
            last_error = f"{type(error).__name__}: {error}"
        time.sleep(1.0)
    raise TimeoutError(f"vLLM server health timeout: {last_error}")


def _stop_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGINT)
    try:
        process.wait(timeout=60)
        return
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=15)
        return
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=15)


def main() -> int:
    args = _parse_args()
    if not args.model.joinpath("config.json").is_file():
        raise FileNotFoundError(args.model)
    if args.output_dir.exists():
        raise FileExistsError(f"refusing to reuse output directory: {args.output_dir}")
    args.output_dir.mkdir(parents=True)
    client_dir = args.output_dir / "client"
    server_log_path = args.output_dir / "server.log"
    iteration_path = args.output_dir / "iteration_timings.tsv"
    marker_path = args.output_dir / "clock_marker_brackets.tsv"

    environment = dict(os.environ)
    python_paths = [
        REPO_ROOT / ".benchmarks" / "clock_marker_injection",
        REPO_ROOT / "src",
        REPO_ROOT / "third_party" / "llm-serving-workloads" / "src",
    ]
    existing_python_path = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = ":".join(
        [*(str(path) for path in python_paths), existing_python_path]
    ).rstrip(":")
    environment.update(
        {
            "ASCEND_RT_VISIBLE_DEVICES": "6",
            "ASCEND_VISIBLE_DEVICES": "6",
            "NO_PROXY": "127.0.0.1,localhost",
            "TORCH_DEVICE_BACKEND_AUTOLOAD": "0",
            "VLLM_HUST_API_KEY": "local-experiment",
            "VLLM_PLUGINS": "ascend",
            "VLLM_RLP_ASCEND_ITERATION_TIMINGS_PATH": str(iteration_path.resolve()),
            "VLLM_RLP_ASCEND_PROFILER_DEVICE_ID": "6",
            "no_proxy": "127.0.0.1,localhost",
        }
    )
    if args.mode == "marker-enabled":
        environment["VLLM_RLP_ASCEND_CLOCK_MARKER_BRACKETS_PATH"] = str(
            marker_path.resolve()
        )
    else:
        environment.pop("VLLM_RLP_ASCEND_CLOCK_MARKER_BRACKETS_PATH", None)

    server_command = [
        str(PYTHON),
        "-m",
        "vllm.entrypoints.openai.api_server",
        "--model",
        str(args.model.resolve()),
        "--served-model-name",
        SERVED_MODEL,
        "--host",
        "127.0.0.1",
        "--port",
        str(args.port),
        "--tensor-parallel-size",
        "1",
        "--max-model-len",
        "4096",
        "--max-num-batched-tokens",
        "4096",
        "--max-num-seqs",
        "4",
        "--gpu-memory-utilization",
        "0.75",
        "--enforce-eager",
        "--generation-config",
        "vllm",
        "--disable-uvicorn-access-log",
    ]
    endpoint = f"http://127.0.0.1:{args.port}"
    client_command = [
        str(PYTHON),
        str(REPO_ROOT / ".benchmarks" / "run_existing_server_trace_probe.py"),
        "--endpoint",
        endpoint,
        "--model",
        SERVED_MODEL,
        "--case-id",
        args.case_id,
        "--seed",
        str(args.seed),
        "--warmup-requests",
        str(args.warmup_requests),
        "--repeat-count",
        str(args.repeat_count),
        "--max-requests",
        str(args.max_requests),
        "--request-max-tokens",
        str(args.request_max_tokens),
        "--measured-concurrency",
        str(args.measured_concurrency),
        "--offered-rate-rps",
        str(args.offered_rate_rps),
        "--measured-duration-s",
        str(args.measured_duration_s),
        "--observer-mode",
        "no-trace",
        "--timeout-s",
        "120",
        "--output-dir",
        str(client_dir.resolve()),
    ]
    provenance = {
        "artifact_label": "real-online v4.4 fixed-rate matched marker overhead",
        "case_id": args.case_id,
        "client_command": client_command,
        "installed_runtime": {
            "vllm_commit": _git_revision(Path("/vllm-workspace/vllm")),
            "vllm_ascend_commit": _git_revision(Path("/vllm-workspace/vllm-ascend")),
        },
        "marker_enabled": args.mode == "marker-enabled",
        "clock_contract_version": "idle-evidence-contract-v4.4",
        "mode": args.mode,
        "model": str(args.model.resolve()),
        "profiler_boundary": "msprof launch ownership around server and matched client",
        "profiler_options": {
            "ai_core": "off",
            "runtime_api": "on",
            "task_time": args.profiler_task_time,
            "type": "db",
        },
        "request_shape": {
            "max_requests": args.max_requests,
            "measured_concurrency": args.measured_concurrency,
            "measured_duration_s": args.measured_duration_s,
            "offered_rate_rps": args.offered_rate_rps,
            "repeat_count": args.repeat_count,
            "request_max_tokens": args.request_max_tokens,
            "seed": args.seed,
            "warmup_requests": args.warmup_requests,
        },
        "server_command": server_command,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "workload_commit": _git_revision(
            REPO_ROOT / "third_party" / "llm-serving-workloads"
        ),
    }
    (args.output_dir / "provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    with server_log_path.open("wb") as server_log:
        server = subprocess.Popen(
            server_command,
            env=environment,
            stdout=server_log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            _wait_for_health(endpoint, server, args.server_timeout_s)
            client = subprocess.run(
                client_command,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            (args.output_dir / "client.stdout").write_bytes(client.stdout)
            if client.returncode != 0:
                raise RuntimeError(f"client probe failed: {client.returncode}")
            summary = json.loads((client_dir / "summary.json").read_text())
            if summary["success_count"] != summary["request_count"]:
                raise RuntimeError(
                    "client probe contained failed requests: "
                    f"{summary['success_count']}/{summary['request_count']}"
                )
            time.sleep(2.0)
        finally:
            _stop_process_group(server)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
