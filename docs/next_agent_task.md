# Next Agent Task: NPU6 Lifecycle Profiler Evidence Push

## Assignment

Use NPU6 and the project conda environment
`vllm-request-lifecycle-profiler-exp`. If the environment does not exist, clone
it from `vllm-hust-dev` first, then install only this repository's overlays and
dependencies into the clone.

Do not use another NPU unless the coordinator explicitly reassigns this project.
Do not mutate the shared `vllm-hust-dev` environment.

## Reproducibility Setup

Start every run from a clean parent-repo view:

```bash
git submodule update --init --recursive
git submodule status --recursive
test ! -L third_party/llm-serving-workloads
make shared-workloads-smoke PYTHON=python3
PYTHONPATH=src pytest -q
```

If `llm-serving-workloads` needs changes, make them in
`third_party/llm-serving-workloads` on a
`feature/request-lifecycle-profiler-workloads` branch, push the branch, then
commit the parent submodule pointer.

## Research Hypothesis

Aggregate TTFT/TPOT and raw runtime logs hide the causal chain behind serving
bottlenecks. A request-lifecycle profiler should produce per-request evidence
that separates tokenizer delay, queueing, prefill saturation, decode jitter, KV
pressure, streaming backpressure, and cleanup stalls.

## Required Experiment Ladder

0. **Current live-service readiness** (`existing-server-probe`): the managed
   baseline is running on NPU6 at `http://127.0.0.1:18168`. The client-observed
   trace probe `.benchmarks/results/npu6_existing_server_trace_probe_smoke/`
   emits `/tmp/codex-vllm-request-lifecycle-profiler-npu6-trace.jsonl`.
   The warmup-controlled repeated suite
   `.benchmarks/results/npu6_existing_server_trace_probe_repeated_smoke/`
   has 1 warmup request plus 12/12 successful measured requests, with measured
   TTFT p50/p95/p99 at 83.43/85.76/86.65 ms. `.benchmarks/results/npu6_trace_probe_preflight/`
   is READY. The matched overhead suite
   `.benchmarks/results/npu6_existing_server_trace_overhead_smoke/` compares
   no-trace and client-proxy trace modes on the same 12-request shape: both
   modes succeed 12/12, trace mode emits 117 events, and TTFT p95 changes by
   +4.07 ms. This is not yet an internal vLLM scheduler/KV trace or internal
   runtime-hook overhead result.
1. **Trace schema coverage** (`derived-artifact`): map every shared workload
   phase to required lifecycle events and mark missing hooks explicitly. Current
   derived diagnosis `.benchmarks/results/npu6_trace_diagnosis/` converts the
   repeated NPU6 proxy trace into stage spans: 13 requests, 117 events, 0.0
   missing-event rate, and 12/12 measured requests attributed to the
   client-visible `decode` span. Decode-proxy p95 is 98.75 ms and
   prefill-proxy p95 is 85.50 ms. Treat this as a stage hypothesis, not
   internal decode root cause.
2. **Controlled client-visible slow-stream diagnosis** (`existing-server-probe`
   plus `derived-artifact`): run `make npu6-existing-server-slow-stream-trace-smoke`
   followed by `make npu6-slow-stream-trace-diagnosis`. Current probe evidence
   at parent commit `6cdbdc9` and diagnosis evidence at parent commit
   `1a0f814` use a streaming-proxy span model with
   `per_chunk_read_delay_ms=80`, 64 output tokens, 1 warmup, and 4 measured
   requests. All measured requests succeed; TTFT p95 is 81.14 ms but latency
   p95 is 5208.20 ms. Diagnosis attributes 4/4 measured requests to
   `streaming` with streaming p95 5127.09 ms and missing-event-rate p95 0.0.
   Treat this as proof that the proxy pipeline can distinguish a controlled
   client-visible backpressure shape from the normal decode-visible trace, not
   as internal runtime diagnosis.
3. **Internal runtime trace hooks** (`real-online` only after repo-launched
   runtime hook instrumentation is active): keep the client-observed proxy
   events as correlation anchors, but add internal vLLM-HUST hooks for
   scheduler admission, queue wait, prefill completion, decode-step progress,
   KV pressure, stream backpressure, and cleanup. Write those internal events
   into the same JSONL schema.
4. **Controlled fault injection** (`real-online` when launched by this repo,
   otherwise `existing-server-probe`): long-prompt surge, decode-heavy batch,
   slow streaming client, KV-pressure boundary, and cleanup stall.
5. **Diagnosis baseline comparison** (`derived-artifact` plus raw traces):
   compare causal attribution against raw logs, simple stage timers, and rules
   disabled.

## Metrics That Must Appear Together

- Attribution accuracy on injected faults with known ground truth.
- False positive and false negative rate per bottleneck class.
- Trace overhead on TTFT/TPOT and memory.
- Event coverage and missing-event rate.
- Time-to-root-cause or scripted diagnosis steps versus raw logs.

Profiler-only results are diagnosis/artifact contributions, not speedups.

## ASPLOS-Level Stop Condition

Keep improving until the profiler can correctly identify the dominant
bottleneck class for controlled faults and reveal at least one non-obvious
serving behavior on shared workloads. A publishable result needs to show why
causal lifecycle evidence changes optimization decisions compared with ordinary
timers, not merely that traces can be collected.

Immediate next step: use the normal proxy diagnosis and the slow-stream proxy
diagnosis as two anchors for internal hook validation. Integrate internal vLLM
hooks so the same trace schema records scheduler admission, queue wait, KV
pressure, prefill, decode, streaming, and cleanup from inside the runtime, then
check whether the internal spans confirm or overturn the proxy `decode` and
client-visible `streaming` hypotheses. Run paired
runtime-hook-disabled/runtime-hook-enabled NPU6 suites using the same
warmup-controlled workload shape, memory snapshots, and the no-trace/trace
client-probe comparison as a sanity bound. Follow with one controlled fault at a
time. Keep client-observed proxy trace results separate from internal runtime
trace claims.

## Paper Update Requirement

After each valid experiment batch, update:

- `docs/claim_ledger.md` with evidence labels and result directories.
- `docs/experiment_plan.md` with any changed fault model or trace schema.
- `paper/request_lifecycle_causal_profiler/request_lifecycle_causal_profiler.tex`
  with only claims supported by the current evidence.
