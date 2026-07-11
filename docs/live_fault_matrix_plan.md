# Live Fault Matrix Plan

The current artifact proves that lifecycle traces can be collected and that
client-visible diagnosis changes under known slow-stream and decode-heavy
faults. That is not yet enough for a systems-paper diagnosis claim. The next
submission-critical milestone is a live fault matrix with ground-truth fault
classes, raw-timer baselines, and explicit overhead measurements.

## Current Supported Evidence

- Synthetic lifecycle attribution: 7/7 deterministic faults are classified
  correctly in the no-NPU harness.
- Client-observed NPU6 proxy traces: warmup-controlled shared workload runs
  produce complete proxy lifecycle events and derived stage hypotheses.
- Runtime hook coverage: the hook-enabled vLLM-HUST submodule records all nine
  lifecycle stages on the NPU6 smoke workload with bounded smoke overhead.
- Controlled slow-stream fault: the known client slow-read fault switches
  client-visible diagnosis to `streaming`, while runtime hooks still record
  complete chains.
- Structured decode-heavy fault: the known decode-heavy workload switches
  client-visible diagnosis to `decode`, while runtime hooks again record
  complete chains.

These results support trace feasibility and coverage during known faults. They
do not yet prove internal-only causal diagnosis accuracy.

## Missing Submission Gates

### Gate 1: Valid Prefill or KV-Pressure Fault

The two long-context candidates in
`.benchmarks/results/npu6_runtime_hooks_long_prefill_fault_smoke/` and
`.benchmarks/results/npu6_runtime_hooks_decode_heavy_fault_smoke/` are invalid
boundary evidence because requests failed before usable runtime attribution.
The next run must find a prompt shape that enters the runtime, produces
successful measured requests, and makes prefill or KV pressure the dominant
stage.

Required evidence:

- `existing-server-probe` or `real-online` result directory on NPU6;
- 1+ warmup and at least 4 measured successful requests;
- client proxy trace and internal `runtime_trace.jsonl`;
- derived diagnosis with measured dominant class;
- runtime trace summary with all nine stages and no missing-stage counts;
- `FAILED.txt` only if the candidate is invalid, with the exact boundary.

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

The current hook-disabled/enabled pair is a small smoke. Before broad overhead
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

## Suggested Next NPU6 Run

Start from the structured decode run that succeeds, then vary prompt shape
while keeping output tokens modest. Prefer a medium prompt that is below the
current 4096-token service boundary but high enough to make prefill visible:

- choose a shared workload or repo-local prompt around 2500-3300 prompt tokens;
- request 16-32 output tokens;
- keep concurrency low first to avoid admission rejection;
- if successful, sweep concurrency 1/2/3 to look for a prefill/KV knee;
- preserve both client proxy and runtime hook traces.

If no valid prefill/KV candidate is found, commit all failed attempts with
`FAILED.txt` and update the plan with the observed service boundary instead of
silently deleting them.
