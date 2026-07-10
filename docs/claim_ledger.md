# Claim Ledger

| Claim | Current status | Required evidence | Forbidden wording |
| --- | --- | --- | --- |
| Lifecycle events can be converted into deterministic stage spans. | Supported by unit tests. | `tests/test_trace.py` passing. | Do not call this causal proof by itself. |
| The profiler attributes injected bottlenecks correctly. | Not yet measured. | NPU6 controlled fault-injection matrix with known ground truth. | Do not claim general diagnosis accuracy from synthetic traces only. |
| The profiler reduces time-to-root-cause compared with raw logs. | Not yet measured. | Human or scripted diagnosis comparison on real traces. | Do not claim performance improvement from profiler-only runs. |

