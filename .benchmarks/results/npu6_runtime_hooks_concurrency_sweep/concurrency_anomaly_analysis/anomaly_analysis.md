# Runtime Concurrency Anomaly Analysis

Evidence label: `derived-artifact`.

Post-hoc analysis of checked-in NPU6 runtime hook traces. It localizes the observed tail to lifecycle spans and metadata already emitted by the runtime hooks; it does not yet prove the sub-stage root cause inside prefill.

| Concurrency | Chains | Prefill p50/p95/max ms | Queue p95 ms | Decode p95 ms | Cached-token ratio p50 | Prefill outliers |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 9 | 64.78/150.31/150.50 | 2.08 | 105.03 | 0.987 | 0 |
| 2 | 9 | 98.67/12261.98/12277.62 | 48.14 | 108.71 | 0.987 | 2 |
| 3 | 9 | 66.38/106.94/107.35 | 49.71 | 110.90 | 0.987 | 0 |

Interpretation:

- The checked-in sweep holds prompt_tokens and generation_tokens constant. The only >1s runtime prefill outliers occur in the concurrency-2 block, while queueing/decode stay small. Current hooks therefore justify the next instrumentation split inside prefill, especially scheduler-output shape, KV allocation/cache state, graph/batch transition, and prefill kernel execution.
- Do not claim KV allocator, graph capture, or kernel root cause from this artifact alone.
