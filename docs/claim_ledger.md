# Claim Ledger

| Claim | Current status | Required evidence | Forbidden wording |
| --- | --- | --- | --- |
| Lifecycle events can be converted into deterministic stage spans. | Supported by unit tests and synthetic schema coverage. | `PYTHONPATH=src pytest -q`; `.benchmarks/results/synthetic_fault_injection_env/matrix.json` with 0.0 missing-event rate for each scenario. | Do not call this causal proof by itself. |
| The profiler distinguishes tokenizer, queueing, prefill, decode, KV pressure, streaming backpressure, and cleanup in deterministic synthetic traces. | Supported as `simulation/model` evidence only. Latest valid result: `.benchmarks/results/synthetic_fault_injection_env/` (`accuracy=1.0`, `false_positive_count=0`, `false_negative_count=0`, `scenario_count=7`). | NPU6 controlled fault-injection matrix with known ground truth before claiming live diagnosis accuracy. | Do not claim general diagnosis accuracy from synthetic traces only. |
| Trace overhead on TTFT/TPOT and memory is low. | Not yet measured. Latest blocked attempt: `.benchmarks/results/npu6_existing_server_probe_blocked/`. | Existing-server probe or repo-launched online run on NPU6 with profiler enabled/disabled and `run_metadata.json`. | Do not infer overhead from no-NPU synthetic attribution. |
| The profiler reduces time-to-root-cause compared with raw logs. | Not yet measured. | Human or scripted diagnosis comparison on real traces. | Do not claim performance improvement from profiler-only runs. |
