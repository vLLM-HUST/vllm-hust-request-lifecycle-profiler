"""Run one smoke-only OASST1 pressure group against an existing service.

This probe changes only client arrival pressure. It does not enable lifecycle
reconciliation or modify runtime scheduling/offload policy. A successful HTTP
response is not sufficient: the caller must validate the closed runtime trace
for a complete preemption/recovery episode.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from vllm_request_lifecycle_profiler.oasst1_workload import (
    DEFAULT_DATA_CACHE,
    OASST1_FILENAME,
    build_oasst1_repetitions,
)

MODEL = "Qwen/Qwen2.5-14B-Instruct"
DEFAULT_ORDINALS = (44, 1, 35, 0, 9, 4)
RECOVERY_TARGET_ORDINAL = 4


def _request_json(
    url: str,
    *,
    body: dict[str, Any],
    request_id: str,
    timeout: float,
) -> tuple[int, dict[str, Any], float]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-Request-Id": request_id},
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return (
                response.status,
                json.loads(raw) if raw else {},
                time.monotonic() - started,
            )
    except urllib.error.HTTPError as error:
        raw = error.read().decode(errors="replace")
        return error.code, {"error": raw}, time.monotonic() - started


def _run_request(
    base_url: str,
    workload_request: Any,
    *,
    delay_seconds: float,
    max_tokens: int,
    timeout: float,
) -> dict[str, Any]:
    time.sleep(delay_seconds)
    submitted_at_ns = time.monotonic_ns()
    status, payload, elapsed = _request_json(
        f"{base_url}/v1/chat/completions",
        body={
            "model": MODEL,
            "messages": workload_request.openai_messages(),
            "max_tokens": max_tokens,
            "temperature": 0.0,
        },
        request_id=workload_request.request_id,
        timeout=timeout,
    )
    choices = payload.get("choices", []) if isinstance(payload, dict) else []
    finish_reason = choices[0].get("finish_reason") if choices else None
    return {
        "request_id": workload_request.request_id,
        "submitted_at_ns": submitted_at_ns,
        "http_status": status,
        "elapsed_seconds": elapsed,
        "finish_reason": finish_reason,
        "usage": payload.get("usage", {}) if isinstance(payload, dict) else {},
        "error": payload.get("error") if status != 200 else None,
    }


def _parse_ordinals(value: str) -> tuple[int, ...]:
    ordinals = tuple(int(item) for item in value.split(","))
    if not ordinals or len(set(ordinals)) != len(ordinals):
        raise argparse.ArgumentTypeError("ordinals must be nonempty and unique")
    if any(ordinal < 0 or ordinal >= 64 for ordinal in ordinals):
        raise argparse.ArgumentTypeError("ordinals must be in [0, 63]")
    if RECOVERY_TARGET_ORDINAL not in ordinals:
        raise argparse.ArgumentTypeError("ordinal 4 recovery target is required")
    return ordinals


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ordinals", type=_parse_ordinals, default=DEFAULT_ORDINALS)
    parser.add_argument("--stagger-ms", type=int, default=200)
    parser.add_argument("--max-tokens", type=int, default=192)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    args = parser.parse_args()
    if args.stagger_ms < 0 or args.max_tokens <= 0 or args.timeout_seconds <= 0:
        parser.error("stagger, max tokens, and timeout must be valid positive values")

    base_url = f"http://127.0.0.1:{args.port}"
    repetition = build_oasst1_repetitions(DEFAULT_DATA_CACHE / OASST1_FILENAME)[0]
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=len(args.ordinals)) as executor:
        futures = {
            executor.submit(
                _run_request,
                base_url,
                repetition[ordinal],
                delay_seconds=position * args.stagger_ms / 1000.0,
                max_tokens=args.max_tokens,
                timeout=args.timeout_seconds,
            ): (position, ordinal)
            for position, ordinal in enumerate(args.ordinals)
        }
        for future in as_completed(futures):
            position, ordinal = futures[future]
            result = future.result()
            result.update({"arrival_position": position, "ordinal": ordinal})
            results.append(result)

    results.sort(key=lambda result: result["arrival_position"])
    output = {
        "schema_version": "issue19-recovery-smoke-client/v1",
        "evidence_class": "smoke-only",
        "treatment_enabled": False,
        "lifecycle_reconcile": False,
        "repetition": 0,
        "recovery_target_ordinal": RECOVERY_TARGET_ORDINAL,
        "arrival_ordinals": list(args.ordinals),
        "stagger_ms": args.stagger_ms,
        "max_tokens": args.max_tokens,
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
