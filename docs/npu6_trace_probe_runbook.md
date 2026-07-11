# NPU6 Existing-Server Trace Probe Runbook

This runbook prepares a read-only probe against an already running vLLM-HUST
OpenAI-compatible server on NPU6. It does not start or stop services. If any
required check fails, write `BLOCKED.txt` and do not switch devices.

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

## Managed Server Launch

The preferred launch path is the vLLM-HUST dev-hub manager with this
repository's non-secret profile:

```bash
cd /home/shuhao/vllm-request-lifecycle-profiler-plugin
export VLLM_HUST_API_KEY='<secret from your local secret store>'
make managed-start
make managed-health
```

The profile is `.benchmarks/profiles/npu6_vllm_hust_trace.env`. It binds
`VLLM_ENGINE_NPU_DEVICES=6`, `ASCEND_RT_VISIBLE_DEVICES=6`, port `18168`, and
the default 7B model. It also points `PYTHONPATH` at this parent repository and
its pinned `third_party/vllm-hust` submodule so hook-enabled evidence is
reproducible from the optimization repository. The profile intentionally does
not set `VLLM_RLP_TRACE_EXPORT_PATH`; hook-disabled mode is the default, and
hook-enabled mode must pass the export path explicitly. Equivalent explicit
command:

```bash
VLLM_ENGINE_ENV_FILE=$PWD/.benchmarks/profiles/npu6_vllm_hust_trace.env \
  /home/shuhao/vllm-hust-dev-hub/manage.sh start
```

Do not use another NPU. If NPU6 is occupied by unrelated work, record a blocked
run and stop. `make managed-stop`, `make managed-status`, and
`make managed-logs` use the same profile.

## Pinned Runtime Hook Submodule

For internal runtime-hook experiments, use the repository-pinned vLLM-HUST
submodule rather than a sibling checkout:

```bash
git submodule update --init --recursive third_party/vllm-hust
git -C third_party/vllm-hust checkout feature/request-lifecycle-profiler-runtime-hooks-faculty
git -C third_party/vllm-hust rev-parse HEAD
```

The expected hook carrier is commit
`7d5406c5a9eab69e8af90e0b17a86c1b207f0a8b`. It imports the parent package's
runtime hook bridge only when `VLLM_RLP_TRACE_EXPORT_PATH` is set. Before
launching a hook-enabled service, install the parent repository into the
project environment:

```bash
conda run --no-capture-output -n vllm-request-lifecycle-profiler-exp \
  python -m pip install -e .
```

Hook-disabled mode leaves `VLLM_RLP_TRACE_EXPORT_PATH` unset. Hook-enabled mode
sets it to a fresh JSONL path, for example:

```bash
export VLLM_RLP_TRACE_EXPORT_PATH=/tmp/codex-vllm-request-lifecycle-profiler-npu6-runtime.jsonl
```

Do not use non-serving import workarounds such as
`TORCH_DEVICE_BACKEND_AUTOLOAD=0` for the measured service. Those are useful
only for local syntax/import diagnostics outside the real Ascend runtime.

## Read-Only Preflight

Run:

```bash
PYTHONPATH=src python3 .benchmarks/preflight_npu6_trace_probe.py \
  --endpoint http://127.0.0.1:18168 \
  --model-path /data/shared_models/Qwen2.5-7B-Instruct \
  --trace-export-path /tmp/codex-vllm-request-lifecycle-profiler-npu6-trace.jsonl \
  --api-token-env VLLM_HUST_API_KEY \
  --output-dir .benchmarks/results/npu6_trace_probe_preflight
```

or:

```bash
make npu6-trace-preflight
```

The script checks:

- the pinned `third_party/llm-serving-workloads` commit and dirty status;
- Ascend runtime root discovery;
- model path existence;
- `GET /v1/models` with optional bearer token;
- trace export file existence and schema;
- `npu-smi info` process ownership on NPU6.

A valid preflight writes `run_metadata.json` without `BLOCKED.txt`. A blocked
preflight writes both `run_metadata.json` and `BLOCKED.txt`; blocked directories
are invalid for paper claims.

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
`request_id`.

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
