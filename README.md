# Request Lifecycle Causal Profiler

This repository is an incubation observability/artifact line for causal request
lifecycle tracing in LLM serving. It targets a single-NPU first implementation
on NPU6 and follows the optimization-repository workflow used by the
`llm-optimizations` workspace.

## Research Question

Can request-level lifecycle traces be converted into causal bottleneck
attribution for LLM serving, so optimization work targets the true limiting
stage instead of correlated symptoms?

## Repository Map

- `src/vllm_request_lifecycle_profiler/`: trace schema, attribution logic, and
  plugin code.
- `.benchmarks/`: trace probes and controlled fault-injection entrypoints.
- `tests/`: no-NPU trace and repository tests.
- `docs/research_logic.md`: seven-step research framing.
- `docs/experiment_plan.md`: evaluation plan and evidence labels.
- `docs/claim_ledger.md`: current claims and forbidden wording.
- `paper/request_lifecycle_causal_profiler/`: systems-paper scaffold.

## Current Mechanism

The initial profiler represents each request as ordered lifecycle events and
computes complete stage spans. The first attribution rule reports the dominant
lifecycle span with a reason code. This is intentionally deterministic so
controlled fault-injection experiments can validate it.

## NPU and Environment

- Reserved device: NPU6.
- Project environment: `vllm-request-lifecycle-profiler-exp`.
- The shared `vllm-hust-dev` environment may be cloned as a baseline, but
  project overlays must not be installed into it.

## Shared Workloads

Use `llm-serving-workloads` as the default workload source. Repo-local workloads
are allowed only for controlled fault-injection cases.

## Evidence Discipline

Every experiment must carry one evidence label: `real-online`,
`existing-server-probe`, `replay`, `simulation/model`, `projected-profile`, or
`derived-artifact`. Profiler-only results are diagnosis evidence, not runtime
speedups.

## Test

```bash
PYTHONPATH=src pytest -q
```

## Next Gate

Run a NPU6 existing-server probe that emits lifecycle timelines, then validate
attribution on controlled long-prompt, decode-heavy, streaming, and KV-pressure
faults.

