# TOP_TIER_PUSH_PLAN

## Target Claim

LLM serving optimization needs causal request lifecycle evidence, not only
aggregate TTFT/TPOT numbers and scattered runtime logs.

## First 72 Hours

Follow `docs/next_agent_task.md` for the current NPU6 execution checklist.

1. Define a stable lifecycle trace schema.
2. Implement a no-op event collector and report generator.
3. Add unit tests for event ordering, missing-event handling, and bottleneck
   classification.
4. Run NPU6 existing-server probes on shared workloads.
5. Add one controlled injected-fault scenario and verify attribution.

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
