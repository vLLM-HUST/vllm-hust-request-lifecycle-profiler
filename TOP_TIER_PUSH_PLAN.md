# TOP_TIER_PUSH_PLAN

[Complete historical original](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/c45a279dd2ee48c57a7cb27a0d7ad0666f25afd5/archive/mod-targeted-20261023/profiler-notes/snapshot/TOP_TIER_PUSH_PLAN.md).
[Evidence and consumer map](docs/notes_evidence.md) distinguishes immutable
historical records, current methods and missing local artifacts. This page
does not claim a new experiment, build, visual review or device admission.

## Target Claim

LLM serving optimization needs causal request lifecycle evidence, not only
aggregate TTFT/TPOT numbers and scattered runtime logs.

## Current claim boundary

Follow [the current research sequence](docs/next_agent_task.md) and
[blind-attribution contract](docs/blind_attribution_contract.md), not an old
completed checklist. Status remains `NOT_M0_PROVEN`; the scoped Issue #19
mechanism `NO_GO` must not be rerun or retuned.

Historical trace capture, pair-plan observations and smoke overhead are
preserved in the complete original and [exact input map](docs/notes_evidence.md).
They are development evidence, not present-day readiness or broad overhead
qualification. The pair-plan summary is a verified external input, not a
tracked result in this source repository.

## Historical method checklist (not execution authorization)

1. Run controlled NPU6 fault attribution one class at a time: slow streaming,
   long-prompt prefill pressure, decode-heavy output, KV-pressure boundary, and
   cleanup stall.
2. Preserve client-observed proxy anchors while collecting internal runtime
   JSONL so each claim can state which layer produced the diagnosis.
3. Compare against raw logs, simple stage timers, and causal rules disabled.
4. Add memory and TPOT overhead for hook-enabled versus hook-disabled modes.
5. Refresh `make top-tier-readiness`, `make paper-assets`, and the paper after
   each valid evidence batch.

## Required Baselines

- raw vLLM/vLLM-HUST logs;
- simple stage timer aggregation;
- manual post-hoc diagnosis;
- profiler with causal rules disabled.

## Claim Discipline

Do not claim a performance optimization unless a policy also changes runtime
behavior. Profiler-only results should be framed as observability, diagnosis,
or artifact contributions.

## Submission Gate

This project is only ASPLOS-ready if causal lifecycle traces correctly
attribute controlled faults, expose a non-obvious real serving bottleneck, and
show why raw logs or simple timers would lead to weaker optimization decisions.
Historical capture readiness is not the causal-evaluation gate. A fresh blind
comparison, baseline advantage and validating counterfactuals remain necessary;
the archived completed checklist does not establish those outcomes.
