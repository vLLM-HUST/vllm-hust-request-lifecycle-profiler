# NPU6 Controlled Fault Matrix

Evidence label: `derived-artifact`.

Benchmark-owned aggregation over checked-in NPU6 existing-server probe and diagnosis artifacts. It is not a repo-launched real-online controlled-fault matrix and must not be used as internal-only diagnosis accuracy.

| Case | Status | Expected | Observed | Correct | Missing-event p95 | Runtime chains |
| --- | --- | --- | --- | --- | --- | --- |
| slow_stream_backpressure | available | streaming | streaming | True | 0.0 | 5/5 |
| structured_decode_heavy | available | decode | decode | True | 0.0 | 5/5 |
| prompt_heavy_low_output | available | prefill | prefill | True | 0.0 | 9/9 |
| concurrency2_prefill_tail | available | prefill | prefill | True | 0.0 | 30/30 |
| queue_pressure | missing_real_online_ground_truth | queueing |  |  |  |  |
| kv_pressure | missing_real_online_ground_truth | kv_pressure |  |  |  |  |
| cleanup_stall | missing_real_online_ground_truth | cleanup |  |  |  |  |

## Missing ASPLOS Gate Items

- This is not a benchmark-owned repo-launched `real-online` matrix.
- Queue pressure, KV pressure, and cleanup stall live faults are missing.
- Raw-log and timed manual diagnosis baselines are not checked in.
- TPOT, CPU, host-memory, and NPU HBM overhead are not measured by this matrix.
