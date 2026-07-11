# Runtime Fault Attribution Roadmap

The repository has passed the trace-capture readiness gate: NPU6 hook-disabled
and hook-enabled source runs are paired, the hook-enabled runtime writes the
full lifecycle schema, and all observed chains contain the required stages.
The next submission-critical question is live attribution accuracy under known
faults.

## Current Runtime Evidence

| Evidence | Result directory | Current meaning |
| --- | --- | --- |
| Hook-disabled baseline | `.benchmarks/results/npu6_runtime_hooks_disabled_low_overhead_baseline/` | Matched NPU6 source row with 12/12 measured success, TTFT p95 80.94 ms, latency p95 179.48 ms |
| Hook-enabled runtime trace | `.benchmarks/results/npu6_runtime_hooks_low_overhead_enabled_smoke/` | 117 internal JSONL events over 13 chains; all chains include received, tokenized, queued, scheduled, prefill_done, first_token, decode_done, stream_done, cleanup_done |
| Pair-plan summary | `.benchmarks/results/npu6_runtime_hook_pair_plan/` | Derived paired gate with complete runtime chains and small-smoke deltas: -2.14 ms TTFT p95 and +0.93 ms latency p95 |
| Slow-stream controlled fault | `.benchmarks/results/npu6_runtime_hooks_slow_stream_fault_smoke/` | Hook-enabled NPU6 run with client slow-read fault: 4/4 measured success, latency p95 5334.74 ms, client diagnosis `streaming` for 4/4 measured requests, and 5/5 complete internal runtime chains |

This evidence proves full lifecycle capture on the smoke path and coverage
during one known client-side slow-stream fault. It does not yet prove
internal-only fault attribution accuracy, memory overhead, TPOT overhead, or
broad workload generality.

## Next Fault Classes

1. Long-prompt prefill pressure: use shared workload long-context shapes and
   verify prefill-dominant attribution without confusing it with queueing.
2. Decode-heavy output: extend output length while holding prompt shape stable
   and verify decode-dominant attribution.
3. KV-pressure boundary: use long-context/burst cases from
   `third_party/llm-serving-workloads` and check whether queue, prefill, or KV
   events become the dominant chain.
4. Cleanup stall: inject or simulate delayed cleanup only if the runtime hook
   boundary can label it honestly.

## Evidence Rules

- Use NPU6 and `vllm-request-lifecycle-profiler-exp`.
- Keep `third_party/vllm-hust` on `feature/request-lifecycle-profiler-runtime-hooks-faculty`
  unless deliberately updating the submodule pointer.
- Run one fault class per result directory and record the injected ground truth
  in `run_metadata.json`.
- Preserve both client-observed anchors and internal runtime JSONL.
- Compare causal attribution with raw logs, simple timers, and causal rules
  disabled before claiming decision impact.
- Rerun `make top-tier-readiness` and `make paper-assets` after each valid
  evidence batch.
