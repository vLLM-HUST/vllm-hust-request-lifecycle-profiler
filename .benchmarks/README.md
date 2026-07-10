# Benchmarks

Benchmark and probe entrypoints for request lifecycle causal profiling.

## Expected Flow

1. Validate trace schema and attribution rules without hardware.
2. Run NPU6 existing-server probes that collect lifecycle timelines.
3. Run controlled fault-injection experiments to measure attribution accuracy.

All run directories must include `run_metadata.json` and an evidence label.
Profiler-only evidence should be framed as diagnosis or artifact evidence, not
runtime optimization.

