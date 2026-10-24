# NPU6 Existing-Server Trace Probe Runbook

[Complete historical original](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/76056993c6bdf615850d683e49c46febf0ce96d3/archive/mod-targeted-20261023/profiler-runbooks/snapshot/docs/npu6_trace_probe_runbook.md).
[Archived inputs and consumer map](runbook_evidence.md) separates historical
results, fresh output examples and unrecovered local traces. No new run is
authorized or claimed by this document migration.

This runbook prepares a read-only probe against an already running vLLM-HUST
OpenAI-compatible server on NPU6. It does not start or stop services. If any
required check fails, write `BLOCKED.txt` and do not switch devices.

> **Current-use warning (2026-08-03):** the commands and legacy three-field
> trace interface below document the earlier Qwen2.5-7B existing-server probe.
> They are not the launch or admission recipe for the newly assigned PR #4 KV
> recovery experiment. PR #4 reconciliation is complete; for that work, finish
> the remaining G0-G2 items in `experiment_plan.md`: freeze the optional
> profile, validate the frozen runtime/device pair, CPU-test the full chain,
> and run a version-aware whole-trace preflight. Do not launch the historical
> `0daab7...` hook carrier for the new #134 run.

## Required Inputs

- Device: NPU6 only.
- Conda environment: `vllm-request-lifecycle-profiler-exp`.
- Endpoint: `VLLM_RLP_ENDPOINT`, for example `http://127.0.0.1:18080`.
- Model path: `VLLM_RLP_MODEL_PATH`; this must be the model served by the
  endpoint.
- API token: set `VLLM_RLP_API_TOKEN` only when the endpoint requires bearer
  authentication. The preflight records whether the env var exists, never the
  token value.
- Trace export path: `VLLM_RLP_TRACE_EXPORT_PATH`, pointing to a JSONL or JSON
  lifecycle trace export emitted by the runtime hook.
- Ascend runtime root: `VLLM_RLP_ASCEND_RUNTIME_ROOT` or an existing
  `ASCEND_HOME_PATH` / `ASCEND_TOOLKIT_HOME` / `ASCEND_ROOT`.

Example:

```bash
export VLLM_RLP_ENDPOINT=http://127.0.0.1:18080
export VLLM_RLP_MODEL_PATH=/path/to/model
export VLLM_RLP_TRACE_EXPORT_PATH=/path/to/request_lifecycle_trace.jsonl
export VLLM_RLP_ASCEND_RUNTIME_ROOT=/usr/local/Ascend/ascend-toolkit/latest
# export VLLM_RLP_API_TOKEN=...  # only if the local endpoint requires it
```

## Historical launch and hook identity

The complete original above preserves the old dev-hub launch commands,
machine-specific paths, profile, hook-carrier SHA and hook-enabled output
example. Those recipes are historical context, not a supported launch base or
authority to start, stop, reinstall or switch an existing service. Do not use
the old carrier for current KV-recovery work. Runtime-hook output must use a
fresh, run-owned external path; it must not overwrite downloaded evidence.

Do not use non-serving import workarounds such as
`TORCH_DEVICE_BACKEND_AUTOLOAD=0` for a measured service. They are only useful
for local syntax/import diagnostics outside the real Ascend runtime.

## Read-Only Preflight

This command is the legacy existing-server preflight, not the versioned
whole-trace KV-recovery admission check. Use the actual authorized endpoint,
served model and current run-owned trace, not an old temporary trace or an
archived READY marker. Choose a new absolute output directory outside the
checkout and outside every downloaded archive root:

```bash
test ! -e "${PROBE_OUTPUT:?choose a new external output directory}" &&
PYTHONPATH=src python3 .benchmarks/preflight_npu6_trace_probe.py \
  --endpoint "${VLLM_RLP_ENDPOINT:?set the authorized endpoint}" \
  --model-path "${VLLM_RLP_MODEL_PATH:?set the served model}" \
  --trace-export-path "${VLLM_RLP_TRACE_EXPORT_PATH:?set the current trace}" \
  --api-token-env VLLM_RLP_API_TOKEN \
  --output-dir "$PROBE_OUTPUT"
```

The script writes metadata and may replace readiness markers in its output
directory; it is read-only with respect to the existing service, not the file
system. Never point it at the verified historical preflight directory.
The legacy `make npu6-trace-preflight` target retains a repo-local default;
the explicit command above avoids that default for new work. No preflight or
service command was executed as part of this document migration.

The script checks:

- the pinned `third_party/llm-serving-workloads` commit and dirty status;
- Ascend runtime root discovery;
- model path existence;
- `GET /v1/models` with optional bearer token;
- trace export file existence and schema;
- `npu-smi info` process ownership on NPU6.

A valid preflight writes `run_metadata.json` and `READY.txt`, removes any stale
`BLOCKED.txt`, and passes only when exactly that marker is present. A blocked
preflight writes `run_metadata.json` and `BLOCKED.txt`, removes any stale
`READY.txt`, and is invalid for paper claims. Both markers present or both
markers absent is an invalid/ambiguous admission state. READY and BLOCKED are
readiness states, not latency, throughput, or profiler-performance results.

## Verifying NPU6 Ownership

Use:

```bash
npu-smi info
```

The process table must show at least one serving process under NPU 6. Record the
PID, process name, and process memory in `run_metadata.json`. If only a local
HTTP proxy is listening but no process appears on NPU6, the probe is not valid
online evidence.

## Trace Hook Interface

The interface in this subsection is the historical proxy/legacy interface. A
valid current P1 trace instead uses versioned `rlp.trace/v1alpha1` records with
canonical `trace_id`/`lifecycle_id`, `event_name`, uint64
`CLOCK_MONOTONIC` `timestamp_ns`, clock-domain identity, process provenance,
loss accounting, and committed process receipts. The PR #4 pressure-episode
fields require the separately frozen optional KV-recovery profile. A current
preflight must validate both schemas and their whole-trace grammar; passing the
legacy `{request_id, stage, timestamp_ms}` check alone is not current READY.

The runtime hook must export one JSON object per lifecycle event, either as
JSONL or as a JSON object with an `events` array. Required fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `request_id` | string | Stable profiler request id used across all events for one user request. |
| `stage` | string | One of the lifecycle stage names below. |
| `timestamp_ms` | number | Monotonic timestamp in milliseconds from a single clock domain. |

Optional fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `metadata` | object | Non-secret stage metadata, such as token counts or KV pressure markers. |
| `sequence_id` | string/int | Runtime sequence id if different from request id. |
| `engine_request_id` | string | vLLM/vLLM-HUST engine request id. |
| `trace_id` | string | End-to-end trace id if propagated by the gateway. |

The hook must emit these stages when observable:

- `received`: API layer accepted the request after authentication.
- `tokenized`: tokenizer finished; include `prompt_tokens` when available.
- `queued`: request entered scheduler/admission queue.
- `scheduled`: scheduler selected the request for execution.
- `prefill_done`: prefill completed; include prompt length and KV allocation
  metadata when available.
- `first_token`: first output token became available.
- `decode_done`: model decode completed.
- `stream_done`: final streaming chunk was flushed to the client.
- `cleanup_done`: request state, KV handles, and stream resources were released.

For KV pressure attribution, emit at least one of these metadata fields on
`scheduled`, `prefill_done`, or `first_token`:

- `kv_pressure: true`
- `kv_cache_pressure_ratio: <float from 0.0 to 1.0>`
- `kv_allocation_wait_ms: <number>`

## Request ID Binding

The gateway should accept an optional client request id header such as
`X-Request-Id`. If unavailable, the hook must export the runtime request id and
the probe client must record the mapping from submitted request to runtime id.
All lifecycle events for the same user request must share the same
`request_id`. For current KV recovery, retain an auditable, untruncated
one-to-one association from the client request ID to canonical `trace_id`, root
lifecycle, engine request/sequence identity, recovery episode, and stable block
identity. The external ID remains bounded/privacy-reviewed noncanonical data;
do not replace it with only a hash and then claim that the complete ID was
preserved.

## Overhead Measurement Contract

Trace overhead must be measured with profiler export disabled and enabled on
the same NPU6 endpoint, model, workload, and runtime settings. Record:

- TTFT median/P95/P99 delta;
- TPOT median/P95/P99 delta;
- request throughput delta;
- host memory and NPU HBM delta;
- trace bytes per request;
- CPU time spent serializing/exporting trace records when available.

Profiler-only runs are diagnosis evidence. They are not serving speedup claims.
