# NPU6 Runtime-Hook Concurrency Sweep

Evidence label: `existing-server-probe` plus `derived-artifact`.

Claim boundary: client-visible lifecycle proxy diagnosis plus runtime-hook schema coverage; not internal-only root-cause proof or KV allocator attribution yet.

| Measured concurrency | Success | TTFT p50/p95 ms | Latency p50/p95 ms | Dominant diagnosis | Prefill p50/p95 ms | Decode p50/p95 ms | Missing event p95 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 9/9 | 77.90/163.30 | 177.91/265.09 | decode {'decode': 7, 'prefill': 2} | 77.66/163.05 | 100.03/103.22 | 0.00 |
| 2 | 9/9 | 116.89/12299.08 | 220.58/12404.06 | prefill {'decode': 1, 'prefill': 8} | 116.75/12298.88 | 102.66/107.45 | 0.00 |
| 3 | 9/9 | 127.06/131.61 | 230.46/234.90 | prefill {'prefill': 9} | 126.92/131.47 | 103.21/109.40 | 0.00 |

Key observations:
- Concurrency 1 is mostly decode-dominant with two prefill outliers.
- Concurrency 2 exposes a severe TTFT/prefill tail: prefill p95 is 12298.88 ms and 8/9 measured requests are prefill-dominant.
- Concurrency 3 stays successful and prefill-dominant for 9/9 measured requests with prefill p95 131.47 ms, showing a non-monotonic scheduling/batching boundary rather than a simple throughput slope.
- Runtime hooks cover 30/30 request chains with all nine stages and no missing stage counts across the sweep.
- Post-hoc internal runtime span analysis confirms the concurrency-2 tail is inside runtime prefill: internal prefill p95 is 12261.98 ms at concurrency 2, versus 150.31 ms at concurrency 1 and 106.94 ms at concurrency 3.

Runtime hook coverage:
- 30/30 complete chains.
- 270 runtime events.
- Missing stage counts: `{}`.
