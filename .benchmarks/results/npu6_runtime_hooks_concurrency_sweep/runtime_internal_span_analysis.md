# Runtime Internal Span Analysis

Evidence label: `derived-artifact`.

Claim boundary: post-hoc analysis of runtime hook timestamps. Concurrency blocks are assigned by chronological order because the three client probes ran sequentially against one hook-enabled service.

| Concurrency | Chains | Runtime total p50/p95 ms | Prefill p50/p95 ms | Decode p50/p95 ms | Queueing p50/p95 ms | Prompt tokens | Generation tokens |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 9 | 175.02/262.24 | 64.78/150.31 | 102.02/105.03 | 1.75/2.08 | 2335-2335 | 8-8 |
| 2 | 9 | 218.29/12400.45 | 98.67/12261.98 | 104.44/108.71 | 1.85/48.14 | 2335-2335 | 8-8 |
| 3 | 9 | 227.35/230.75 | 66.38/106.94 | 105.78/110.90 | 43.17/49.71 | 2335-2335 | 8-8 |

Interpretation:
- Compare this table with `concurrency_sweep_summary.md` before making internal root-cause claims.
