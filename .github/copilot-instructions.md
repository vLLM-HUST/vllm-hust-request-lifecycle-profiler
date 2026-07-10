# GitHub Copilot Instructions

## Repository Role

- Repository: `vllm-request-lifecycle-profiler-plugin`
- Purpose: causal request lifecycle tracing and bottleneck attribution for LLM
  serving.
- Initial NPU binding: NPU6.
- Project conda environment: `vllm-request-lifecycle-profiler-exp`.

## Critical Boundary

- Use this repository as the parent artifact for profiler code, trace schema,
  benchmark probes, paper assets, and reproducibility metadata.
- Do not install overlays or project-specific dependencies into the shared
  `vllm-hust-dev` baseline. Clone a project-specific conda environment first.
- If runtime source changes become necessary, add repo-owned submodules or patch
  branches and use `feature/...` branch names inside submodules.

## Working Rules

- Keep trace/profiler logic under `src/`, benchmark probes under `.benchmarks/`,
  and paper-facing artifacts under `paper/`.
- Use the sibling or submodule `llm-serving-workloads` repository as the default
  workload source.
- Repo-local workloads are allowed only for controlled fault-injection cases.
- Label every result as `real-online`, `existing-server-probe`, `replay`,
  `simulation/model`, `projected-profile`, or `derived-artifact`.
- Do not claim performance improvement from profiler-only changes.
- Do not create `.venv` or `venv`.

## Research Focus

Prioritize causal attribution over raw telemetry volume. Required baselines are
raw logs, simple stage timers, manual diagnosis, and profiler reports with
causal rules disabled.

## Testing

```bash
PYTHONPATH=src pytest -q
```
