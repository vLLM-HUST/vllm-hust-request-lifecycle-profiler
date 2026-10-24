# Benchmarks

[Complete historical original](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/db79a80ae22f974e31d19fd84ba2a20ed919290c/archive/mod-targeted-20261023/profiler-entry-docs/snapshot/.benchmarks/README.md).
[Evidence and consumer map](../docs/entry_evidence.md); historical observations are not current
readiness or performance qualification. Status remains `NOT_M0_PROVEN`.

Benchmark and probe entrypoints for request lifecycle causal profiling.

## Expected Flow

1. Validate trace schema and attribution rules without hardware.
2. Run NPU6 existing-server probes that collect lifecycle timelines.
3. Pair hook-disabled and hook-enabled runtime runs under the same workload.
4. Run controlled live fault-injection experiments to measure attribution
   accuracy.

All run directories must include `run_metadata.json` and an evidence label.
Profiler-only evidence should be framed as diagnosis or artifact evidence, not
runtime optimization.

## Historical inputs and current consumers

`make npu6-runtime-hook-pair-plan` consumes verified external
`BENCHMARK_COLLECTION_ROOT` inputs, not checked-in runs. It creates a fresh
derived summary; historical capture completeness does not establish current
device readiness, blind accuracy or broad overhead qualification.

Use [EVIDENCE.md](../EVIDENCE.md) to fetch and verify inputs and
[the NPU probe runbook](../docs/npu6_trace_probe_runbook.md) to distinguish
historical profiles, schema preflight and fresh authorized collection. A
preflight is not a workload execution or performance result. Do not launch a
service from old documentation without verifying current hardware ownership.

`top-tier-readiness` includes tests and multiple derived-output consumers;
it is not a read-only inspection command. Keep new outputs separate from the
verified archival roots. The scoped Issue #19 `NO_GO` remains unchanged.
