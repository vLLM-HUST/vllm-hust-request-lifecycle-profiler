# Benchmark Workspace

This directory is the template home for workload-driven benchmark and smoke-test
entrypoints.

Derived repositories should keep reproducible shared-workload harnesses here,
not in the repository root.

The checked-in `run_shared_workloads_smoke.py` script is intentionally minimal:
it validates that a template-derived repository can consume the full repo-local
shared workload suite from `llm-serving-workloads` without keeping a local copy
of those workload definitions.