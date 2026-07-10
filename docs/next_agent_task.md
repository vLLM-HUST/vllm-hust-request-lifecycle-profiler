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
   phase to required lifecycle events and mark missing hooks explicitly.
2. **Internal runtime trace hooks** (`real-online` only after repo-launched
   runtime hook instrumentation is active): keep the client-observed proxy
   events as correlation anchors, but add internal vLLM-HUST hooks for
   scheduler admission, queue wait, prefill completion, decode-step progress,
   KV pressure, stream backpressure, and cleanup. Write those internal events
   into the same JSONL schema.
3. **Controlled fault injection** (`real-online` when launched by this repo,
   otherwise `existing-server-probe`): long-prompt surge, decode-heavy batch,
   slow streaming client, KV-pressure boundary, and cleanup stall.
4. **Diagnosis baseline comparison** (`derived-artifact` plus raw traces):
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

Immediate next step: integrate internal vLLM hooks so the same trace schema
records scheduler admission, queue wait, KV pressure, prefill, decode,
streaming, and cleanup from inside the runtime. Then run paired
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
