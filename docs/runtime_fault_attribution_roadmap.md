# Runtime Fault Attribution Roadmap

[Complete historical original](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/db79a80ae22f974e31d19fd84ba2a20ed919290c/archive/mod-targeted-20261023/profiler-entry-docs/snapshot/docs/runtime_fault_attribution_roadmap.md).
[Evidence and consumer map](entry_evidence.md); historical observations are not current
readiness or performance qualification. Status remains `NOT_M0_PROVEN`.

## Current scope

Follow [the current research sequence](next_agent_task.md), not the archived
dated queue. The scoped Issue #19 mechanism `NO_GO` remains unchanged. Historical
hook pairs, slow-stream/decode probes, concurrency anomalies and failed
long-context candidates remain in the complete original and raw collection.
The [member map](entry_evidence_bindings.json) identifies every legacy input.

Complete smoke capture is not causal diagnosis accuracy. The coarse prefill
anomaly does not identify a mechanism; invalid long-context candidates remain
boundary evidence. Memory/TPOT overhead, blind baseline advantage and broad
generality are not established by these records. No rerun is implied.

## Evidence Rules

- Use NPU6 and `vllm-request-lifecycle-profiler-exp`.
- Treat the old `third_party/vllm-hust`
  `feature/request-lifecycle-profiler-runtime-hooks-faculty` pointer as a
  historical reproducer, not the new integration base. Use the approved exact
  runtime/device pair and record any newly approved compatibility SHA.
- Run one fault class per result directory and record the injected ground truth
  in `run_metadata.json`.
- Preserve both client-observed anchors and internal runtime JSONL.
- Compare causal attribution with raw logs, simple timers, and causal rules
  disabled before claiming decision impact.
- Rerun `make top-tier-readiness` and `make paper-assets` after each valid
  evidence batch.
