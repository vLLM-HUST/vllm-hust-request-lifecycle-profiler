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
- Boundary: these are client-observed events (`received`, local tokenization,
  HTTP send, first streamed chunk, stream done, cleanup). They are not yet
  internal vLLM scheduler/KV/preemption events and the matched overhead suite
  must not be used as internal runtime-hook or memory-overhead evidence.

Next step:
instrument internal vLLM-HUST lifecycle hooks under the same trace schema so
the NPU6 traces contain scheduler admission, prefill completion, decode-step
progress, KV pressure, stream backpressure, and cleanup events from inside the
runtime. Keep the client proxy events as correlation anchors, not as substitutes
for internal runtime spans.

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
