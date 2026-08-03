# Historical and Development Case Table

All rows are contaminated or otherwise ineligible for primary blind scoring.
They are useful for normalizer, phase-DAG, invalid-case, and regression tests.
Numbers below describe the checked-in evidence at profiler parent
`84261a2458e1f961b0279b70780ca9497bad3f2e`; they are not new measurements.
One row may aggregate multiple source and derived artifacts, but every
individual artifact retains exactly one repository evidence label.

| Development case | Checked-in observation | Evidence/ground-truth boundary | Allowed use |
| --- | --- | --- | --- |
| Synthetic seven-fault matrix | 7/7 deterministic scenarios attributed as modeled, with zero missing-event rate | `simulation/model`; not a server or Ascend causal result | Schema, scorer, and deterministic normalization tests |
| Public prefix candidate `vllm-hust#163` | Public issue reports a same-spec prefix-repetition throughput regression and names candidate version intervals | Public issue candidate; no new reproduction is recorded here and its identity is exposed | Team-A reproduction planning and development replay only; never reveal the issue identity in a primary blind pack |
| Public core candidates `vllm-hust#151` | Public issue lists six first-parent performance jumps and prioritizes two intervals for alternating reproduction | Public issue candidate with mostly single-run historical data; not causal evidence | Team-A reproduction planning and development replay only; Remygred consumes a redacted blind pack rather than duplicating the reproduction owner |
| Public Ascend candidate `vllm-ascend-hust#145` | Public issue reports multi-card online regressions across an Ascend version interval | Public issue candidate; multi-card and already exposed, with no new reproduction recorded here | Team-A reproduction planning and development replay only; never a fresh opaque primary case as named |
| Runtime hook off/on smoke pair | Both modes 12/12 successful; enabled-minus-disabled TTFT p95 `-2.14 ms`, latency p95 `+0.93 ms`; enabled trace has 13/13 complete chains | Small `existing-server-probe` plus derived pair plan; no TPOT, CPU, host memory, or HBM bound | Exporter/trace readiness and overhead harness development |
| Slow-stream client fault | 4/4 measured success; latency p95 `5334.74 ms`; client diagnosis is streaming for 4/4; runtime has 5/5 complete chains | Client-side injected slow read; does not prove internal streaming root cause | Streaming, delivery, and cross-layer disagreement tests |
| Structured decode-heavy shape | 4/4 measured success; latency p95 `2135.82 ms`; client decode span p95 `1986.54 ms`; runtime has 5/5 complete chains | Known decode-heavy workload plus proxy diagnosis; not blind internal diagnosis | Decode boundary and candidate-ranking development |
| Prompt-heavy, low-output shape | 8/8 measured success; TTFT p95 `133.89 ms`; client prefill span p95 `133.66 ms`; runtime has 9/9 complete chains | Known workload shape; not a blind or isolated internal mechanism | Prefill boundary and short-output tests |
| Concurrency-2 coarse-prefill tail | At concurrency 2, TTFT p95 `12299.08 ms` and runtime-prefill p95 `12261.98 ms`; the two greater-than-one-second outliers occur only there | Observation localized to coarse prefill; not controlled KV, allocator, graph, or kernel ground truth | Residual, abstention, and finer-span design tests |
| Long-context candidate failures | Each attempted candidate produced 4/4 failed measured requests and no usable positive latency sample | Source label `existing-server-probe`; validity `invalid_boundary` because the service limit was hit before attribution | Invalid-case and target-admission tests |

Source artifact families in the private parent include:

- `.benchmarks/results/npu6_runtime_hook_pair_plan/`
- `.benchmarks/results/npu6_runtime_hooks_slow_stream_fault_smoke/`
- `.benchmarks/results/npu6_runtime_hooks_slow_stream_fault_diagnosis/`
- `.benchmarks/results/npu6_runtime_hooks_structured_decode_fault_smoke/`
- `.benchmarks/results/npu6_runtime_hooks_structured_decode_fault_diagnosis/`
- `.benchmarks/results/npu6_runtime_hooks_prompt_heavy_low_output_smoke/`
- `.benchmarks/results/npu6_runtime_hooks_prompt_heavy_low_output_diagnosis/`
- `.benchmarks/results/npu6_runtime_hooks_concurrency_sweep/`
- `.benchmarks/results/npu6_runtime_hooks_long_prefill_fault_smoke/`
- `.benchmarks/results/npu6_runtime_hooks_decode_heavy_fault_smoke/`

Team A must rotate or create opaque cases for M0. Renaming these rows or hiding
their labels after Team B has seen them does not restore blindness.

The inherited `vllm-hust#185` acceptance metrics remain mandatory:
critical-path share, attribution precision, time-to-localize, trace overhead,
and cross-run variance. Issue #1 additionally requires top-k confidence,
unexplained residual, abstention, top-1/top-3 accuracy, MRR, and
wrong-attribution severity. Historical reproduction owners provide redacted
case inputs through Team A; this profiler task owns normalization, ranking, and
counterfactual evaluation rather than duplicating their root-cause work.
