# Contributing

This repository is the parent artifact for the request lifecycle causal profiler
research line.

## Rules

1. Use `vllm-request-lifecycle-profiler-exp` for project work. Do not install
   overlays into the shared `vllm-hust-dev` environment.
2. Use `llm-serving-workloads` as the default shared workload source.
3. Keep repo-local workloads only for controlled fault-injection cases.
4. Label every result as `real-online`, `existing-server-probe`, `replay`,
   `simulation/model`, `projected-profile`, or `derived-artifact`.
5. Do not claim runtime speedup from profiler-only instrumentation.
6. If a runtime submodule is added later, create feature branches named
   `feature/request-lifecycle-profiler-<purpose>`.

## Test

```bash
PYTHONPATH=src pytest -q
```

