from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from itertools import pairwise
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

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


def _git_dirty_excluding(cwd: Path, excluded: Path) -> bool | str:
    try:
        excluded_rel = excluded.resolve().relative_to(cwd.resolve())
    except ValueError:
        return _git_dirty(cwd)
    try:
        status = subprocess.check_output(
            ["git", "status", "--short", "--", ".", f":(exclude){excluded_rel}"],
            cwd=cwd,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return bool(status)


def _now_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0


def _stream_token_ids(payload: bytes) -> list[int] | None:
    """Return delta token IDs from one decoded SSE JSON payload.

    ``None`` means that the frame carries no token-bearing choice (for
    example a finish or usage frame). A token-bearing choice without the
    requested token IDs is rejected so frame timestamps can never be
    mislabeled as token timestamps.
    """

    decoded = json.loads(payload)
    if not isinstance(decoded, dict) or not isinstance(decoded.get("choices"), list):
        raise ValueError("SSE payload must contain a choices list")
    token_ids: list[int] = []
    saw_token_ids = False
    for choice in decoded["choices"]:
        if not isinstance(choice, dict):
            raise ValueError("SSE choice must be an object")
        choice_token_ids = choice.get("token_ids")
        if choice_token_ids is None:
            if choice.get("text"):
                raise ValueError("token-bearing SSE choice lacks token_ids")
            continue
        if not isinstance(choice_token_ids, list) or any(
            isinstance(token_id, bool) or not isinstance(token_id, int)
            for token_id in choice_token_ids
        ):
            raise ValueError("SSE choice token_ids must be an integer list")
        if choice.get("text") and not choice_token_ids:
            raise ValueError("token-bearing SSE choice has empty token_ids")
        saw_token_ids = True
        token_ids.extend(choice_token_ids)
    return token_ids if saw_token_ids else None


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
    per_chunk_read_delay_ms: float,
    proxy_stage_mode: str,
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
            # vLLM returns delta token IDs for each streaming choice. Token
            # latency metrics must use these IDs rather than treating SSE
            # frames as one-token observations.
            "return_token_ids": True,
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
    last_data_chunk_ms: float | None = None
    token_arrival_ms: list[float] = []
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
                    arrival_ms = _now_ms(start)
                    last_data_chunk_ms = arrival_ms
                    try:
                        delta_token_ids = _stream_token_ids(
                            stripped.removeprefix(b"data: ")
                        )
                    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                        error = "invalid_sse_token_payload"
                        break
                    if delta_token_ids:
                        token_arrival_ms.extend(
                            arrival_ms for _ in delta_token_ids
                        )
                    if delta_token_ids and not first_token_seen:
                        first_token_seen = True
                        ts = arrival_ms
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
                    if per_chunk_read_delay_ms > 0:
                        time.sleep(per_chunk_read_delay_ms / 1000.0)
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
        decode_done_ms = end_ms
        decode_done_metadata: dict[str, Any] = {
            "observer": "client_probe",
            "stream_chunk_count": chunk_count,
            "proxy_stage_mode": proxy_stage_mode,
        }
        if proxy_stage_mode == "streaming-proxy":
            decode_done_ms = first_token_ms or last_data_chunk_ms or end_ms
            decode_done_metadata["meaning"] = "client_visible_decode_boundary_for_streaming_proxy"
            decode_done_metadata["per_chunk_read_delay_ms"] = per_chunk_read_delay_ms
        events.append(
            _event(
                request_id=request_id,
                stage=LifecycleStage.DECODE_DONE,
                timestamp_ms=decode_done_ms,
                metadata=decode_done_metadata,
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
    inter_token_latency_ms = [
        current - previous
        for previous, current in pairwise(token_arrival_ms)
    ]
    tpot_ms = (
        (token_arrival_ms[-1] - token_arrival_ms[0])
        / (len(token_arrival_ms) - 1)
        if len(token_arrival_ms) > 1
        else None
    )
    return {
        "request_id": request_id,
        "ok": bool(status and 200 <= status < 300 and not error),
        "status": status,
        "error": error,
        "latency_ms": latency_ms,
        "first_token_ms": first_token_ms,
        "inter_token_latency_ms": inter_token_latency_ms,
        "generated_token_count": len(token_arrival_ms),
        "stream_chunk_count": chunk_count,
        "stream_byte_count": byte_count,
        "token_timing_source": "sse_choice_token_ids",
        "tpot_ms": tpot_ms,
        "events": events,
    }


def _metadata(args: argparse.Namespace) -> dict[str, Any]:
    dirty_exclusion_dir = getattr(args, "dirty_exclusion_dir", None) or args.output_dir
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
        "seed": args.seed,
        "measured_concurrency": getattr(args, "measured_concurrency", 1),
        "offered_rate_rps": args.offered_rate_rps,
        "measured_duration_s": args.measured_duration_s,
        "observer_mode": args.observer_mode,
        "per_chunk_read_delay_ms": args.per_chunk_read_delay_ms,
        "proxy_stage_mode": args.proxy_stage_mode,
        "repo": {
            "path": str(REPO_ROOT),
            "branch": _git(["branch", "--show-current"]),
            "commit": _git(["rev-parse", "HEAD"]),
            "dirty": _git_dirty(REPO_ROOT),
            "dirty_excluding_output_dir": _git_dirty_excluding(REPO_ROOT, dirty_exclusion_dir),
            "dirty_exclusion_dir": str(dirty_exclusion_dir),
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
    events_lock = threading.Lock()
    measured_concurrency = max(1, int(getattr(args, "measured_concurrency", 1)))

    def run_one(
        *,
        row: Any,
        request_id: str,
        phase: str,
        repeat: int,
        index: int,
        scheduled_offset_s: float | None = None,
        benchmark_start: float | None = None,
    ) -> dict[str, Any]:
        actual_start_offset_s = (
            time.perf_counter() - benchmark_start
            if benchmark_start is not None
            else None
        )
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
            per_chunk_read_delay_ms=args.per_chunk_read_delay_ms,
            proxy_stage_mode=args.proxy_stage_mode,
        )
        result_events = result.pop("events")
        if result_events:
            with events_lock:
                events.extend(result_events)
        result.update(
            {
                "phase": phase,
                "repeat": repeat,
                "case_index": index,
                "scheduled_offset_s": scheduled_offset_s,
                "actual_start_offset_s": actual_start_offset_s,
                "schedule_lag_ms": (
                    (actual_start_offset_s - scheduled_offset_s) * 1000.0
                    if actual_start_offset_s is not None
                    and scheduled_offset_s is not None
                    else None
                ),
                "completed_offset_s": (
                    time.perf_counter() - benchmark_start
                    if benchmark_start is not None
                    else None
                ),
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

    record_specs = [
        (repeat, index, row)
        for repeat in range(args.repeat_count)
        for index, row in enumerate(rows)
    ]
    measured_started = time.perf_counter()
    if args.offered_rate_rps > 0:
        if args.measured_duration_s <= 0:
            raise ValueError(
                "--measured-duration-s must be positive with open-loop load"
            )
        scheduled_count = math.ceil(
            args.offered_rate_rps * args.measured_duration_s - 1e-12
        )
        if scheduled_count != len(record_specs):
            raise ValueError(
                "repeat-count * selected request count must equal the fixed-rate "
                f"schedule count ({len(record_specs)} != {scheduled_count})"
            )
        with ThreadPoolExecutor(max_workers=measured_concurrency) as executor:
            future_to_seq = {}
            for sequence, (repeat, index, row) in enumerate(record_specs):
                scheduled_offset_s = sequence / args.offered_rate_rps
                delay_s = measured_started + scheduled_offset_s - time.perf_counter()
                if delay_s > 0:
                    time.sleep(delay_s)
                future = executor.submit(
                    run_one,
                    row=row,
                    request_id=f"{args.case_id}::repeat{repeat}::{index}",
                    phase="measured",
                    repeat=repeat,
                    index=index,
                    scheduled_offset_s=scheduled_offset_s,
                    benchmark_start=measured_started,
                )
                future_to_seq[future] = sequence
            completed_records: list[tuple[int, dict[str, Any]]] = []
            for future in as_completed(future_to_seq):
                completed_records.append((future_to_seq[future], future.result()))
            records.extend(
                record
                for _, record in sorted(
                    completed_records, key=lambda item: item[0]
                )
            )
    elif measured_concurrency == 1:
        for repeat, index, row in record_specs:
            records.append(
                run_one(
                    row=row,
                    request_id=f"{args.case_id}::repeat{repeat}::{index}",
                    phase="measured",
                    repeat=repeat,
                    index=index,
                )
            )
    else:
        with ThreadPoolExecutor(max_workers=measured_concurrency) as executor:
            future_to_seq = {}
            sequence = 0
            for repeat, index, row in record_specs:
                future = executor.submit(
                    run_one,
                    row=row,
                    request_id=f"{args.case_id}::repeat{repeat}::{index}",
                    phase="measured",
                    repeat=repeat,
                    index=index,
                )
                future_to_seq[future] = sequence
                sequence += 1
            completed_records: list[tuple[int, dict[str, Any]]] = []
            for future in as_completed(future_to_seq):
                completed_records.append((future_to_seq[future], future.result()))
            records.extend(record for _, record in sorted(completed_records, key=lambda item: item[0]))
    measured_duration_s = time.perf_counter() - measured_started

    success = [record for record in records if record["ok"]]
    warmup_success = [record for record in warmup_records if record["ok"]]
    first_tokens = [float(record["first_token_ms"]) for record in success if record["first_token_ms"] is not None]
    latencies = [float(record["latency_ms"]) for record in success]
    inter_token_latencies = [
        float(value)
        for record in success
        for value in record["inter_token_latency_ms"]
    ]
    tpots = [
        float(record["tpot_ms"])
        for record in success
        if record["tpot_ms"] is not None
    ]
    output_chunk_count = sum(int(record["stream_chunk_count"]) for record in success)
    schedule_lags_ms = [
        float(record["schedule_lag_ms"])
        for record in records
        if record["schedule_lag_ms"] is not None
    ]
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
            "measured_concurrency": measured_concurrency,
            "observer_mode": args.observer_mode,
            "offered_rate_rps": args.offered_rate_rps,
            "fixed_offered_window_s": (
                args.measured_duration_s if args.offered_rate_rps > 0 else None
            ),
            "schedule_lag_ms": _numeric_summary(schedule_lags_ms),
            "warmup_first_token_ms": _numeric_summary(warmup_first_tokens),
            "warmup_latency_ms": _numeric_summary(warmup_latencies),
            "first_token_ms": _numeric_summary(first_tokens),
            "latency_ms": _numeric_summary(latencies),
            "inter_token_latency_ms": _numeric_summary(inter_token_latencies),
            "tpot_ms": _numeric_summary(tpots),
            "measured_duration_s": measured_duration_s,
            "request_throughput_per_s": (
                len(success) / measured_duration_s if measured_duration_s else 0.0
            ),
            "output_chunk_count": output_chunk_count,
            "output_chunk_throughput_per_s": (
                output_chunk_count / measured_duration_s
                if measured_duration_s
                else 0.0
            ),
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
    parser.add_argument("--measured-concurrency", type=int, default=1)
    parser.add_argument(
        "--offered-rate-rps",
        type=float,
        default=0.0,
        help="Positive value enables deterministic open-loop arrivals.",
    )
    parser.add_argument(
        "--measured-duration-s",
        type=float,
        default=0.0,
        help="Fixed offered-load window; required with --offered-rate-rps.",
    )
    parser.add_argument("--request-max-tokens", type=int, default=8)
    parser.add_argument("--observer-mode", choices=("trace", "no-trace"), default="trace")
    parser.add_argument("--per-chunk-read-delay-ms", type=float, default=0.0)
    parser.add_argument(
        "--proxy-stage-mode",
        choices=("decode-proxy", "streaming-proxy"),
        default="decode-proxy",
    )
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--timeout-s", type=float, default=60.0)
    parser.add_argument("--trace-export-path", type=Path, default=DEFAULT_TRACE_EXPORT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--dirty-exclusion-dir",
        type=Path,
        help=(
            "Generated artifact root excluded from source-cleanliness checks. "
            "Changes anywhere else still make the run dirty."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    result = run_probe(args)
    write_outputs(args, result)
    print(json.dumps({"output_dir": str(args.output_dir), **result["summary"]}, sort_keys=True))


if __name__ == "__main__":
    main()
