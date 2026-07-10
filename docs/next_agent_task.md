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
   baseline is running on NPU6 at `http://127.0.0.1:18168`; endpoint auth,
   model path, and NPU6 process checks pass. The current preflight remains
   blocked only because
   `/tmp/codex-vllm-request-lifecycle-profiler-npu6-trace.jsonl` is not being
   emitted. This is the mechanism-integration gap to fix.
1. **Trace schema coverage** (`derived-artifact`): map every shared workload
   phase to required lifecycle events and mark missing hooks explicitly.
2. **Existing-server trace probe** (`existing-server-probe`): collect timelines
   on NPU6 without changing runtime behavior and report overhead.
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

Immediate next step: wire the lifecycle trace exporter into the managed vLLM
runtime so `VLLM_RLP_TRACE_EXPORT_PATH` is written for normal `/v1/completions`
or chat requests. Once the file appears, rerun `make npu6-trace-preflight` and
then run the controlled fault matrix on the same endpoint.

## Paper Update Requirement

After each valid experiment batch, update:

- `docs/claim_ledger.md` with evidence labels and result directories.
- `docs/experiment_plan.md` with any changed fault model or trace schema.
- `paper/request_lifecycle_causal_profiler/request_lifecycle_causal_profiler.tex`
  with only claims supported by the current evidence.
