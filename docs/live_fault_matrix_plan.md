# Live Fault Matrix Plan

[Complete historical original](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/76056993c6bdf615850d683e49c46febf0ce96d3/archive/mod-targeted-20261023/profiler-runbooks/snapshot/docs/live_fault_matrix_plan.md).
[Archived inputs and consumer map](runbook_evidence.md) separates historical
results, fresh output examples and unrecovered local traces. No new run is
authorized or claimed by this document migration.

This is a historical method plan, not current environment admission or a new
execution queue. The active research direction and scoped Issue #19 `NO_GO`
boundary are maintained in [next_agent_task.md](next_agent_task.md) and
[blind_attribution_contract.md](blind_attribution_contract.md).
Status remains `NOT_M0_PROVEN`.

## Historical evidence boundary

The complete original records synthetic coverage, client-proxy observations,
runtime-hook smoke, controlled faults and a concurrency-sensitive prefill
anomaly. Numerical observations are archive-only. These support development
trace feasibility, not internal-only causal accuracy or broad overhead claims.
The [input map](runbook_evidence.md) links the existing raw-data capsule and
exact members; an available summary does not recover an omitted raw trace.

## Missing Submission Gates

### Gate 1: Valid Prefill or KV-Pressure Fault

The historical long-context candidates remain invalid boundary evidence:
requests failed before usable runtime attribution. The prompt-heavy case and
concurrency sweep are separate development evidence, not replacements for
blind evaluation. See the archived original and [input map](runbook_evidence.md)
for the preserved cases. A coarse prefill tail is not KV-mechanism proof.
The methodological gap is finer decomposition of scheduler-to-prefill,
KV allocation/cache pressure, graph/batch transition and kernel execution.

Required evidence:

- Read the verified external concurrency-sweep inputs and chain-level audit
  through [the exact member map](runbook_evidence.md), never this checkout's
  `.benchmarks/results` directory.
- Add finer internal span or counter analysis for the concurrency-2 tail:
  scheduler-to-prefill transition, prefill execution, KV allocation/cache
  pressure, graph capture or batch transition, and request-level token counts.
- Preserve client proxy trace and internal `runtime_trace.jsonl`.
- Report whether internal evidence confirms a KV/prefill mechanism or
  overturns the proxy hypothesis.
- Use `FAILED.txt` only if a follow-up candidate is invalid, with the exact
  boundary.

### Gate 2: Raw-Timer Baseline Comparison

The paper must show why lifecycle attribution changes the optimization decision
relative to ordinary timers. The next derived artifact should compare, for each
controlled fault, what a timer-only observer can conclude versus what the
lifecycle spans conclude.

Required rows:

- normal shared workload;
- slow-stream fault;
- decode-heavy fault;
- valid prefill/KV fault once found.

Required columns:

- TTFT p95 and latency p95;
- timer-only likely diagnosis;
- lifecycle dominant span;
- next optimization action under timer-only reasoning;
- next optimization action under lifecycle reasoning;
- whether the two actions differ.

### Gate 3: Runtime Hook Overhead Beyond Smoke

The historical hook-disabled/enabled pair is a small smoke. Before broad overhead
claims, add at least one longer decode-heavy workload and one prompt-heavy
workload.

Required metrics:

- TTFT p50/p95 delta;
- latency p50/p95 delta;
- TPOT or per-token decode latency delta when token counts are available;
- trace bytes per request;
- process RSS/HBM snapshot before and after the run;
- complete-chain coverage.

### Gate 4: Claim Discipline

Use these terms until all gates close:

- "runtime hook coverage during known faults";
- "client-visible diagnosis";
- "derived optimization decision aid";
- "candidate prefill/KV fault boundary".

Do not use these terms yet:

- "internal-only causal diagnosis accuracy";
- "root cause is proven by runtime hooks";
- "broadly negligible overhead";
- "time-to-root-cause reduction" unless a raw-log/manual baseline is measured.

## Historical follow-up method (not execution authorization)

Do not launch another coarse-prefill run yet. After G0-G2 admit the environment,
run one minimal controlled pressure episode and split its chain into D2H/H2D
copy, restore-to-wakeup, wakeup-to-admission, admission-to-first-compute,
requeue/wait, and total recovery while preserving explicit request/sequence/
block and transfer handoffs. Then execute the fixed-8-GiB matched modes defined
in `experiment_plan.md`.

The old concurrency-2 shape may be reused later as a pressure trigger or
secondary control after the recovery profile is live, but it cannot substitute
for #134's Qwen2.5-14B, 32K-context target. If a run has no real recovery
episode, mark negative coverage; if admission or trace validation fails, keep
the exact BLOCKED/FAILED artifact rather than silently deleting it.
