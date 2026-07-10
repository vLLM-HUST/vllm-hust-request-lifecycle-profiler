# Benchmarks

Benchmark and probe entrypoints for request lifecycle causal profiling.

## Expected Flow

1. Validate trace schema and attribution rules without hardware.
2. Run NPU6 existing-server probes that collect lifecycle timelines.
3. Run controlled fault-injection experiments to measure attribution accuracy.

All run directories must include `run_metadata.json` and an evidence label.
Profiler-only evidence should be framed as diagnosis or artifact evidence, not
runtime optimization.

Use `preflight_npu6_trace_probe.py` before an existing-server probe. It checks
the endpoint, authentication, model path, Ascend runtime root, NPU6 ownership,
trace export schema, and pinned workload submodule metadata without launching or
killing any service.

The repo also provides a non-secret vLLM-HUST dev-hub profile at
`profiles/npu6_vllm_hust_trace.env`. Use:

```bash
make managed-start
make managed-health
make npu6-trace-preflight
```

The preflight is readiness evidence only until real workload requests and trace
exports are collected.
