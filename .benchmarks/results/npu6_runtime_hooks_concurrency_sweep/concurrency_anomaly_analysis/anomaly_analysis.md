# Runtime Concurrency Anomaly Analysis

Evidence label: `derived-artifact`.

Post-hoc analysis of checked-in NPU6 runtime hook traces. It localizes the observed tail to lifecycle spans and metadata already emitted by the runtime hooks; it does not yet prove the sub-stage root cause inside prefill.

| Concurrency | Chains | Prefill p50/p95/max ms | Queue p95 ms | Decode p95 ms | Cached-token ratio p50 | Prefill outliers |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 9 | 64.78/150.31/150.50 | 2.08 | 105.03 | 0.987 | 0 |
| 2 | 9 | 98.67/12261.98/12277.62 | 48.14 | 108.71 | 0.987 | 2 |
| 3 | 9 | 66.38/106.94/107.35 | 49.71 | 110.90 | 0.987 | 0 |

## Diagnostic Status

- Localized lifecycle stage: `prefill`.
- Root-cause status: `unresolved`.
- The current `scheduled` to `prefill_done` span does not separate scheduler handoff, KV/cache work, graph or batch transitions, and device kernel execution.

## Required Sub-prefill Instrumentation

| Component | Required fields absent from this trace | Disambiguating question |
| --- | --- | --- |
| `scheduler_to_prefill` | `scheduler_dispatch_timestamp_ms`, `worker_prefill_start_timestamp_ms`, `scheduled_batch_size`, `scheduled_prefill_tokens` | Is the tail in scheduler-to-worker handoff or after prefill starts? |
| `kv_allocation_cache_pressure` | `kv_allocation_duration_ms`, `kv_blocks_requested`, `kv_blocks_allocated`, `kv_free_blocks_before`, `kv_free_blocks_after` | Does KV allocation or cache pressure consume the prefill span? |
| `graph_batch_transition` | `execution_mode`, `graph_key`, `graph_capture_or_compile_duration_ms`, `previous_batch_shape`, `current_batch_shape` | Does a graph capture, compile, or batch-shape transition explain the tail? |
| `prefill_kernel_execution` | `prefill_kernel_start_timestamp_ms`, `prefill_kernel_end_timestamp_ms`, `prefill_device_duration_ms`, `attention_backend` | Is the delay inside device execution, and on which prefill path? |

Interpretation:

- The checked-in sweep holds prompt_tokens and generation_tokens constant. The only >1s runtime prefill outliers occur in the concurrency-2 block, while queueing/decode stay small. Current hooks therefore justify the next instrumentation split inside prefill, especially scheduler-output shape, KV allocation/cache state, graph/batch transition, and prefill kernel execution.
- Do not claim KV allocator, graph capture, or kernel root cause from this artifact alone.
