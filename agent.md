# Agent Handoff

## Mission

Advance this repository as the single-NPU NPU6 observability line for causal
request-lifecycle tracing in LLM serving.

## Rules

- Use the project conda environment `vllm-request-lifecycle-profiler-exp`.
- Use `third_party/llm-serving-workloads` as the pinned shared workload source
  for paper evidence.
- Keep controlled fault-injection workloads in this repository when they are
  specific to lifecycle attribution.
- Label every result as `real-online`, `existing-server-probe`, `replay`,
  `simulation/model`, `projected-profile`, or `derived-artifact`.
- Treat profiler-only results as diagnosis evidence, not runtime speedups.

## Current Focus

Upgrade client-observed lifecycle traces into runtime-stage attribution, then
validate the attribution with controlled long-prompt, decode-heavy, streaming,
and KV-pressure cases.

## Useful Entry Points

- `README.md`
- `docs/research_logic.md`
- `docs/experiment_plan.md`
- `docs/claim_ledger.md`
- `docs/next_agent_task.md`
- `.benchmarks/README.md`
- `paper/request_lifecycle_causal_profiler/`
