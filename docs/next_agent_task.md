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

The runtime hook carrier is already pinned as
`third_party/vllm-hust` on branch
`feature/request-lifecycle-profiler-runtime-hooks-faculty`, commit `0daab7a30`. Do not
reintegrate hook sites from scratch. Use this submodule as the runtime source
for the next hook-enabled NPU6 launch.

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
   events as correlation anchors. The pinned vLLM-HUST submodule already emits
   optional hook stages for `received`, `tokenized`, `queued`, `scheduled`,
   `prefill_done`, `first_token`, `decode_done`, `stream_done`, and
   `cleanup_done` through the parent bridge when `VLLM_RLP_TRACE_EXPORT_PATH`
   is set. The next job is to launch that submodule on NPU6 and collect paired
   hook-disabled and hook-enabled suites.
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

Current paired runtime-hook evidence is available. The disabled source run
`.benchmarks/results/npu6_runtime_hooks_disabled_low_overhead_baseline/` has
12/12 measured success, TTFT p95 80.94 ms, and latency p95 179.48 ms. The
enabled source run `.benchmarks/results/npu6_runtime_hooks_low_overhead_enabled_smoke/`
has 12/12 measured success, TTFT p95 78.80 ms, latency p95 180.41 ms, and
29,159 bytes of runtime JSONL. `make npu6-runtime-hook-pair-plan` aggregates
these into `.benchmarks/results/npu6_runtime_hook_pair_plan/`, reporting
-2.14 ms TTFT p95 and +0.93 ms latency p95. The runtime JSONL contains 117
events over 13 external request chains, and all 13 chains include `received`,
`tokenized`, `queued`, `scheduled`, `prefill_done`, `first_token`,
`decode_done`, `stream_done`, and `cleanup_done`.

Immediate next step: continue the hook-enabled controlled-fault matrix. The
slow-stream client fault is now measured at
`.benchmarks/results/npu6_runtime_hooks_slow_stream_fault_smoke/` with 4/4
measured success, client-visible `streaming` diagnosis for 4/4 measured
requests, and 5/5 complete internal runtime hook chains. The structured
decode-heavy fault is now measured at
`.benchmarks/results/npu6_runtime_hooks_structured_decode_fault_smoke/` with
4/4 measured success, client-visible `decode` diagnosis for 4/4 measured
requests, decode-span p95 1986.54 ms, and 5/5 complete internal runtime hook
chains. The prompt-heavy low-output fault is now measured at
`.benchmarks/results/npu6_runtime_hooks_prompt_heavy_low_output_smoke/` with
8/8 measured success, client-visible `prefill` diagnosis for 8/8 measured
requests, prefill-span p95 133.66 ms, decode-span p95 36.70 ms, and 9/9
complete internal runtime hook chains. The concurrency-sensitive sweep is now
measured at `.benchmarks/results/npu6_runtime_hooks_concurrency_sweep/`: all
27 measured requests across concurrency 1/2/3 succeed, runtime hooks cover
30/30 complete chains, and concurrency 2 exposes a severe client-visible
prefill/TTFT tail (8/9 `prefill`, TTFT p95 12299.08 ms, prefill-span p95
12298.88 ms) that does not appear at concurrency 3 (9/9 `prefill`, TTFT p95
131.61 ms). Treat this as the strongest current candidate prefill/KV or
scheduler boundary, but not as internal KV proof yet. Do not reuse the invalid
`.benchmarks/results/npu6_runtime_hooks_long_prefill_fault_smoke/` or
`.benchmarks/results/npu6_runtime_hooks_decode_heavy_fault_smoke/` as positive
evidence; they are marked `FAILED.txt` because the candidate workload failed
before usable attribution. Next, repeat and instrument the concurrency-2 tail:
preserve the client-observed proxy trace as a correlation anchor, collect the
internal runtime JSONL, add internal request-level fields if needed (scheduler
wait, prefill execution, KV allocation/cache pressure, graph capture or batch
transition, prompt/generation tokens), and report whether internal spans
confirm or overturn the proxy hypothesis. Keep client-observed proxy trace
results separate from internal runtime trace claims.

Before the next run, read `docs/live_fault_matrix_plan.md`. The plan defines
the stricter ASPLOS gate: existing slow-stream and decode-heavy results prove
runtime-hook coverage during known faults, but not internal-only causal
diagnosis accuracy. The next useful NPU6 work is internal correlation for the
concurrency-2 anomaly, plus a raw-timer baseline comparison showing why
lifecycle spans change the optimization decision.

## Paper Update Requirement

After each valid experiment batch, update:

- `docs/claim_ledger.md` with evidence labels and result directories.
- `docs/experiment_plan.md` with any changed fault model or trace schema.
- `paper/request_lifecycle_causal_profiler/request_lifecycle_causal_profiler.tex`
  with only claims supported by the current evidence.
