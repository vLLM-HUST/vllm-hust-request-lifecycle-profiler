# Experiment Plan

## Phase 0: Trace Schema Validation

- Unit-test lifecycle event ordering, missing stages, and bottleneck
  attribution rules.
- Generate synthetic traces for known tokenizer delay, queueing, prefill,
  decode, KV pressure, streaming backpressure, and cleanup bottlenecks.
- Report attribution accuracy, false positives, false negatives, complete span
  coverage, and missing-event rate. Trace overhead is out of scope for this
  phase because no serving runtime is launched.

Evidence label: `simulation/model`.

Latest valid no-NPU result:
`.benchmarks/results/synthetic_fault_injection_env/`, generated in
`vllm-request-lifecycle-profiler-exp`, reports 7/7 correct synthetic
attributions, zero false positives, zero false negatives, and zero missing-event
rate across all deterministic fault cases. This supports schema/harness
coverage only; it does not support live NPU6 diagnosis or speedup claims.

## Phase 1: Existing-Server Probe on NPU6

- Follow `docs/npu6_trace_probe_runbook.md` before probing any server.
- Instrument baseline serving without changing runtime behavior.
- Run shared workloads and emit per-request timelines.
- Compare profiler reports against raw logs and simple stage timers.

Evidence label: `existing-server-probe`.

Latest attempt:
`.benchmarks/results/npu6_existing_server_probe_blocked/` records that NPU6 was
visible with no `npu-smi` process owner, but no project-defined existing-server
endpoint, model identity, request client, or trace export hook was available.
This is a blocked/invalid probe directory and must not support paper claims.

Readiness preflight and first trace probe:
`.benchmarks/preflight_npu6_trace_probe.py` now defines the repo-local
read-only preflight. It verifies endpoint authentication, `/v1/models`, model
path, Ascend runtime root, NPU6 process ownership, trace export schema, and the
pinned workload submodule commit. If a runtime trace hook is missing, the
preflight records the missing hook as `trace_export_invalid:*` rather than
claiming an online measurement.

Current live trace evidence:

- `.benchmarks/results/npu6_existing_server_trace_probe_smoke/` is an
  `existing-server-probe` client-observed lifecycle proxy trace. It sent 4
  streaming requests to the managed NPU6 endpoint, all succeeded, and emitted
  36 JSONL lifecycle events to
  `/tmp/codex-vllm-request-lifecycle-profiler-npu6-trace.jsonl`.
- `.benchmarks/results/npu6_trace_probe_preflight/` now contains `READY.txt`;
  the trace export schema check passed with 36 records and no missing required
  fields.
- `.benchmarks/results/npu6_existing_server_trace_probe_repeated_smoke/`
  upgrades the probe to a warmup-controlled repeated suite. It sent 1 warmup
  request plus 12 measured streaming requests to the managed NPU6 endpoint,
  all measured requests succeeded, and the measured TTFT summary was p50 83.43
  ms, p95 85.76 ms, and p99 86.65 ms. This removes the first-request warmup
  outlier from the measured summary and gives a stable baseline for later
  enabled/disabled overhead comparisons.
- `.benchmarks/results/npu6_existing_server_trace_overhead_smoke/` is the
  matched no-trace/trace client-probe overhead suite. Each mode sent 12 measured
  streaming requests with 12/12 success. Trace mode emitted 117 client-observed
  lifecycle events. Relative to no-trace, trace mode changed TTFT p95 by
  +4.07 ms and latency p95 by +4.03 ms. This supports a narrow proxy-overhead
  claim for client-side event construction only.
- `.benchmarks/results/npu6_trace_diagnosis/` is a `derived-artifact`
  diagnosis pass over the repeated NPU6 trace probe. It converts 117
  client-observed events into per-request spans for 13 requests with 0.0
  missing-event rate. Among the 12 measured requests, the dominant
  client-visible span is `decode` for 12/12 requests. Decode-proxy p95 is
  98.75 ms and prefill-proxy p95 is 85.50 ms. This is useful because it turns
  raw TTFT/latency into a per-request stage hypothesis, but it remains a
  client-visible proxy diagnosis rather than an internal runtime root cause.
- Boundary: these are client-observed events (`received`, local tokenization,
  HTTP send, first streamed chunk, stream done, cleanup). They are not yet
  internal vLLM scheduler/KV/preemption events and the matched overhead suite
  must not be used as internal runtime-hook or memory-overhead evidence.
- `.benchmarks/results/npu6_existing_server_slow_stream_trace_smoke/` adds a
  controlled client-visible slow-stream shape. It uses the same managed NPU6
  endpoint, `proxy_stage_mode=streaming-proxy`, `per_chunk_read_delay_ms=80`,
  two repeated measured requests over two shared-workload rows, and a
  64-token output cap. All 4 measured requests succeeded. TTFT p95 stayed
  81.14 ms while latency p95 rose to 5208.20 ms. The derived artifact
  `.benchmarks/results/npu6_slow_stream_trace_diagnosis/` attributes 4/4
  measured requests to the `streaming` span with streaming p95 5127.09 ms and
  missing-event-rate p95 0.0. This is client-visible backpressure evidence,
  not internal runtime streaming or scheduler evidence.

Runtime hook integration readiness:
the pinned `third_party/vllm-hust` submodule is on
`feature/request-lifecycle-profiler-runtime-hooks-faculty` at commit `0daab7a30`. It
adds an optional dependency-free shim that imports
`vllm_request_lifecycle_profiler.runtime_hooks` only when
`VLLM_RLP_TRACE_EXPORT_PATH` is set, then emits internal events for request
receipt, tokenization, queue admission, scheduling, prefill completion, first
token, decode completion, stream handoff, and cleanup.

Current paired runtime-hook evidence:
`.benchmarks/results/npu6_runtime_hooks_disabled_low_overhead_baseline/` and
`.benchmarks/results/npu6_runtime_hooks_low_overhead_enabled_smoke/` run the same
warmup-controlled shared-workload shape from the pinned submodule. Both source
runs are `existing-server-probe` evidence with clean `dirty_excluding_output_dir`
metadata and 12/12 successful measured requests. The enabled run writes
`.benchmarks/results/npu6_runtime_hooks_low_overhead_enabled_smoke/runtime_trace.jsonl`
with 117 internal runtime events over 13 external request chains. The derived
pair-plan `.benchmarks/results/npu6_runtime_hook_pair_plan/` reports 13/13
complete chains with all nine stages present and no missing stages. Current
overhead on this small smoke is -3.66 ms TTFT p50, -2.14 ms TTFT p95,
-4.28 ms latency p50, and +0.93 ms latency p95 for hook-enabled versus
hook-disabled, after replacing per-event open/write/close with a persistent
append fd sink.

Next step:
the first hook-enabled controlled fault is now checked in at
`.benchmarks/results/npu6_runtime_hooks_slow_stream_fault_smoke/`. It reruns
the slow-stream client fault while preserving both the client proxy trace and
the internal runtime JSONL. The client diagnosis
`.benchmarks/results/npu6_runtime_hooks_slow_stream_fault_diagnosis/`
attributes 4/4 measured requests to `streaming`; the runtime trace summary
records 45 internal events over 5/5 complete chains with all nine stages
present. This closes the "hook coverage during a known fault" gap for
slow-stream, but it is not yet internal-only diagnosis accuracy. The next
hook-enabled decode-heavy fault is also checked in at
`.benchmarks/results/npu6_runtime_hooks_structured_decode_fault_smoke/`, with
derived diagnosis in
`.benchmarks/results/npu6_runtime_hooks_structured_decode_fault_diagnosis/`.
It uses `shared_scenario_structured_agent_decode` with 128 requested output
tokens, records 4/4 measured success, and attributes 4/4 measured requests to
`decode` with decode-span p95 1986.54 ms while runtime hooks again record 5/5
complete chains.

Two attempted long-context candidates are intentionally marked invalid:
`.benchmarks/results/npu6_runtime_hooks_long_prefill_fault_smoke/` and
`.benchmarks/results/npu6_runtime_hooks_decode_heavy_fault_smoke/` both failed
before usable runtime-hook attribution. Treat them as service-boundary evidence
for workload design, not as attribution failures. The next submission-critical
gap is a valid prefill-pressure or KV-pressure fault under the same
hook-enabled pattern.

The stricter live-fault matrix gate is documented in
`docs/live_fault_matrix_plan.md`. It separates current coverage claims from the
missing ASPLOS-level diagnosis claims: valid prefill/KV ground truth,
timer-only baseline comparison, TPOT/HBM overhead beyond the smoke workload,
and a larger workload matrix.

## Phase 2: Controlled Fault Injection

- Inject tokenizer slow path, queue surge, long-prompt prefill, decode-heavy
  output, KV pressure boundary, slow streaming client, and cleanup stall
  conditions.
- Measure whether attribution matches injected ground truth.

Evidence label: `real-online` only when the runtime actually serves requests on
NPU6; otherwise use `replay` or `simulation/model`.

## Required Artifact Fields

Every run directory must include `run_metadata.json` with parent commit,
environment, NPU id, model, runtime, workload source, injected fault, command,
dirty state, and evidence label.
