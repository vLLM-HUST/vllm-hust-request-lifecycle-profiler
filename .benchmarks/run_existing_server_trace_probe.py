from __future__ import annotations

import argparse
from datetime import datetime
from datetime import timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.request import Request
from urllib.request import urlopen

from vllm_request_lifecycle_profiler.shared_workloads import generate_case_requests
from vllm_request_lifecycle_profiler.trace import LifecycleStage


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKLOAD_REPO = REPO_ROOT / "third_party" / "llm-serving-workloads"
DEFAULT_TRACE_EXPORT = Path("/tmp/codex-vllm-request-lifecycle-profiler-npu6-trace.jsonl")
DEFAULT_OUTPUT_DIR = REPO_ROOT / ".benchmarks" / "results" / "npu6_existing_server_trace_probe_smoke"


class WhitespaceTokenizer:
    def encode(self, text: str, add_special_tokens: bool = False) -> list[str]:
        del add_special_tokens
        return text.split()


def _git(args: list[str], *, cwd: Path = REPO_ROOT) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _git_dirty(cwd: Path) -> bool | str:
    status = _git(["status", "--short"], cwd=cwd)
    if status == "unknown":
        return "unknown"
    return bool(status)


def _now_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0


def _event(
    *,
    request_id: str,
    stage: LifecycleStage,
    timestamp_ms: float,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "stage": stage.value,
        "timestamp_ms": timestamp_ms,
        "metadata": metadata or {},
    }


def _stream_completion(
    *,
    endpoint: str,
    api_key: str,
    model: str,
    prompt: str,
    max_tokens: int,
    timeout_s: float,
    request_id: str,
    tokenizer: WhitespaceTokenizer,
    collect_events: bool,
) -> dict[str, Any]:
    start = time.perf_counter()
    events: list[dict[str, Any]] = []
    if collect_events:
        events.append(
            _event(
                request_id=request_id,
                stage=LifecycleStage.RECEIVED,
                timestamp_ms=0.0,
                metadata={"observer": "client_probe"},
            )
        )
    prompt_tokens = len(tokenizer.encode(prompt, add_special_tokens=False))
    if collect_events:
        events.append(
            _event(
                request_id=request_id,
                stage=LifecycleStage.TOKENIZED,
                timestamp_ms=_now_ms(start),
                metadata={"observer": "client_probe", "prompt_tokens_proxy": prompt_tokens},
            )
        )
        events.append(
            _event(
                request_id=request_id,
                stage=LifecycleStage.QUEUED,
                timestamp_ms=_now_ms(start),
                metadata={"observer": "client_probe", "meaning": "request_ready_to_send"},
            )
        )
    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": 0.0,
            "stream": True,
        }
    ).encode("utf-8")
    request = Request(
        endpoint.rstrip("/") + "/v1/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        method="POST",
    )
    if collect_events:
        events.append(
            _event(
                request_id=request_id,
                stage=LifecycleStage.SCHEDULED,
                timestamp_ms=_now_ms(start),
                metadata={"observer": "client_probe", "meaning": "http_request_sent"},
            )
        )
    chunk_count = 0
    byte_count = 0
    status: int | None = None
    error = ""
    first_token_seen = False
    first_token_ms: float | None = None
    try:
        with urlopen(request, timeout=timeout_s) as response:
            status = response.status
            while True:
                line = response.readline()
                if not line:
                    break
                byte_count += len(line)
                stripped = line.strip()
                if not stripped:
                    continue
                if line.startswith(b"data: ") and stripped != b"data: [DONE]":
                    chunk_count += 1
                    if not first_token_seen:
                        first_token_seen = True
                        ts = _now_ms(start)
                        first_token_ms = ts
                        if collect_events:
                            events.append(
                                _event(
                                    request_id=request_id,
                                    stage=LifecycleStage.PREFILL_DONE,
                                    timestamp_ms=ts,
                                    metadata={"observer": "client_probe", "meaning": "first_stream_chunk"},
                                )
                            )
                            events.append(
                                _event(
                                    request_id=request_id,
                                    stage=LifecycleStage.FIRST_TOKEN,
                                    timestamp_ms=ts,
                                    metadata={"observer": "client_probe"},
                                )
                            )
    except HTTPError as exc:
        status = exc.code
        error = f"http_{exc.code}"
    except (TimeoutError, URLError, OSError) as exc:
        error = type(exc).__name__
    end_ms = _now_ms(start)
    if not first_token_seen and collect_events:
        events.append(
            _event(
                request_id=request_id,
                stage=LifecycleStage.PREFILL_DONE,
                timestamp_ms=end_ms,
                metadata={"observer": "client_probe", "missing_first_token": True},
            )
        )
        events.append(
            _event(
                request_id=request_id,
                stage=LifecycleStage.FIRST_TOKEN,
                timestamp_ms=end_ms,
                metadata={"observer": "client_probe", "missing_first_token": True},
            )
        )
    if collect_events:
        events.append(
            _event(
                request_id=request_id,
                stage=LifecycleStage.DECODE_DONE,
                timestamp_ms=end_ms,
                metadata={"observer": "client_probe", "stream_chunk_count": chunk_count},
            )
        )
        events.append(
            _event(
                request_id=request_id,
                stage=LifecycleStage.STREAM_DONE,
                timestamp_ms=end_ms,
                metadata={"observer": "client_probe", "stream_byte_count": byte_count},
            )
        )
        events.append(
            _event(
                request_id=request_id,
                stage=LifecycleStage.CLEANUP_DONE,
                timestamp_ms=_now_ms(start),
                metadata={"observer": "client_probe"},
            )
        )
    latency_ms = events[-1]["timestamp_ms"] if events else end_ms
    return {
        "request_id": request_id,
        "ok": bool(status and 200 <= status < 300 and not error),
        "status": status,
        "error": error,
        "latency_ms": latency_ms,
        "first_token_ms": first_token_ms,
        "stream_chunk_count": chunk_count,
        "stream_byte_count": byte_count,
        "events": events,
    }


def _metadata(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "evidence_label": "existing-server-probe",
        "result_valid_for_speedup_claims": False,
        "trace_boundary": (
            "Client-observed lifecycle proxy trace. It records request preparation, HTTP send, "
            "first streamed chunk, stream completion, and cleanup from the probe process; it is "
            "not yet an internal vLLM scheduler/KV trace."
        ),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "command": [Path(sys.argv[0]).name, *sys.argv[1:]],
        "endpoint": args.endpoint,
        "model": args.model,
        "trace_export_path": str(args.trace_export_path),
        "case_id": args.case_id,
        "max_requests": args.max_requests,
        "warmup_requests": args.warmup_requests,
        "repeat_count": args.repeat_count,
        "observer_mode": args.observer_mode,
        "repo": {
            "path": str(REPO_ROOT),
            "branch": _git(["branch", "--show-current"]),
            "commit": _git(["rev-parse", "HEAD"]),
            "dirty": _git_dirty(REPO_ROOT),
        },
        "workload_source": {
            "path": str(WORKLOAD_REPO.relative_to(REPO_ROOT)),
            "commit": _git(["rev-parse", "HEAD"], cwd=WORKLOAD_REPO),
            "dirty": _git_dirty(WORKLOAD_REPO),
        },
        "api_key_env": args.api_key_env,
        "api_key_present": bool(os.environ.get(args.api_key_env, "")),
    }


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    api_key = os.environ.get(args.api_key_env, "")
    if not api_key:
        raise SystemExit(f"missing API token env: {args.api_key_env}")
    tokenizer = WhitespaceTokenizer()
    collect_events = args.observer_mode == "trace"
    rows = generate_case_requests(args.case_id, seed=args.seed)[: args.max_requests]
    warmup_rows = rows[: args.warmup_requests]
    records: list[dict[str, Any]] = []
    warmup_records: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []

    def run_one(*, row: Any, request_id: str, phase: str, repeat: int, index: int) -> dict[str, Any]:
        result = _stream_completion(
            endpoint=args.endpoint,
            api_key=api_key,
            model=args.model,
            prompt=str(row.prompt),
            max_tokens=min(int(row.output_len), args.request_max_tokens),
            timeout_s=args.timeout_s,
            request_id=request_id,
            tokenizer=tokenizer,
            collect_events=collect_events,
        )
        events.extend(result.pop("events"))
        result.update(
            {
                "phase": phase,
                "repeat": repeat,
                "case_index": index,
            }
        )
        return result

    for index, row in enumerate(warmup_rows):
        warmup_records.append(
            run_one(
                row=row,
                request_id=f"{args.case_id}::warmup::{index}",
                phase="warmup",
                repeat=0,
                index=index,
            )
        )

    for repeat in range(args.repeat_count):
        for index, row in enumerate(rows):
            records.append(
                run_one(
                    row=row,
                    request_id=f"{args.case_id}::repeat{repeat}::{index}",
                    phase="measured",
                    repeat=repeat,
                    index=index,
                )
            )

    success = [record for record in records if record["ok"]]
    warmup_success = [record for record in warmup_records if record["ok"]]
    first_tokens = [float(record["first_token_ms"]) for record in success if record["first_token_ms"] is not None]
    latencies = [float(record["latency_ms"]) for record in success]
    warmup_first_tokens = [
        float(record["first_token_ms"]) for record in warmup_success if record["first_token_ms"] is not None
    ]
    warmup_latencies = [float(record["latency_ms"]) for record in warmup_success]
    return {
        "metadata": _metadata(args),
        "summary": {
            "warmup_request_count": len(warmup_records),
            "warmup_success_count": len(warmup_success),
            "request_count": len(records),
            "success_count": len(success),
            "error_count": len(records) - len(success),
            "event_count": len(events),
            "observer_mode": args.observer_mode,
            "warmup_first_token_ms": _numeric_summary(warmup_first_tokens),
            "warmup_latency_ms": _numeric_summary(warmup_latencies),
            "first_token_ms": _numeric_summary(first_tokens),
            "latency_ms": _numeric_summary(latencies),
        },
        "warmup_records": warmup_records,
        "records": records,
        "events": events,
    }


def _numeric_summary(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "min": None, "p50": None, "p95": None, "p99": None, "max": None}
    ordered = sorted(values)

    def percentile(p: float) -> float:
        if len(ordered) == 1:
            return ordered[0]
        rank = (len(ordered) - 1) * p
        lower = int(rank)
        upper = min(lower + 1, len(ordered) - 1)
        weight = rank - lower
        return ordered[lower] * (1.0 - weight) + ordered[upper] * weight

    return {
        "count": len(values),
        "min": ordered[0],
        "p50": percentile(0.50),
        "p95": percentile(0.95),
        "p99": percentile(0.99),
        "max": ordered[-1],
    }


def write_outputs(args: argparse.Namespace, result: dict[str, Any]) -> None:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.observer_mode == "trace":
        args.trace_export_path.parent.mkdir(parents=True, exist_ok=True)
        with args.trace_export_path.open("w", encoding="utf-8") as handle:
            for event in result["events"]:
                handle.write(json.dumps(event, sort_keys=True) + "\n")
    (args.output_dir / "run_metadata.json").write_text(
        json.dumps(result["metadata"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "probe_results.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "summary.json").write_text(
        json.dumps(result["summary"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an existing-server client-observed lifecycle trace probe.")
    parser.add_argument("--endpoint", default=os.environ.get("VLLM_RLP_ENDPOINT", "http://127.0.0.1:18168"))
    parser.add_argument("--model", default=os.environ.get("VLLM_ENGINE_SERVED_MODEL_NAME", "codex-qwen2.5-7b-npu6"))
    parser.add_argument("--api-key-env", default="VLLM_HUST_API_KEY")
    parser.add_argument("--case-id", default="shared_scenario_multi_turn_knowledge_service")
    parser.add_argument("--max-requests", type=int, default=4)
    parser.add_argument("--warmup-requests", type=int, default=0)
    parser.add_argument("--repeat-count", type=int, default=1)
    parser.add_argument("--request-max-tokens", type=int, default=8)
    parser.add_argument("--observer-mode", choices=("trace", "no-trace"), default="trace")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--timeout-s", type=float, default=60.0)
    parser.add_argument("--trace-export-path", type=Path, default=DEFAULT_TRACE_EXPORT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    result = run_probe(args)
    write_outputs(args, result)
    print(json.dumps({"output_dir": str(args.output_dir), **result["summary"]}, sort_keys=True))


if __name__ == "__main__":
    main()
