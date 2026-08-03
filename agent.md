# Agent Handoff

The authoritative repository instructions are in `AGENTS.md`; keep this file
as a short compatibility handoff only.

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

Follow the 2026-08-03 KV-recovery correction in `AGENTS.md`: preserve committed
P1 checkpoint `9f1464b8d017ef48e66b8b4c9bd4a5a37fdc563d`, reconcile merged profiler PR #4,
freeze the optional KV-recovery and required communication/specialty profile, then attach
the full request/sequence/recovery chain to the approved runtime/device pair.
Do not run tiering under the existing `communication_mode=none`, and do not
treat a BLOCKED preflight as performance evidence. The first hardware work is
a single admitted pressure-episode trace smoke; matched #134 runs follow only
after all CPU, compatibility, and readiness gates pass.

## Useful Entry Points

- `README.md`
- `docs/research_logic.md`
- `docs/experiment_plan.md`
- `docs/claim_ledger.md`
- `docs/next_agent_task.md`
- `.benchmarks/README.md`
- `paper/request_lifecycle_causal_profiler/`
