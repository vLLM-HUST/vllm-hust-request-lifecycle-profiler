# G6 Completion Record (2026-08-11)

> Gate: **G6 — counterfactual** (experiment_plan.md step 7).
> Verdict: **PASS** (development-level rank-one counterfactual). This is
> **NOT blind-scored**; blind M0 scoring requires the separately frozen
> Team-A custody/reveal protocol.

## 1. Requirement checklist

| # | Requirement | Delivered |
|---|-------------|-----------|
| 1 | causal ranking selects rank-1 mechanism | ✅ H2D restore / KV-recovery state machine (only mechanism with observable phase delta from G4/G5) |
| 2 | change ONLY the rank-1 mechanism variable | ✅ matched pair: base `tiering_enabled` vs head `tiering_disabled` at fixed 8 GiB; D2H offload, capacity, model, hardware, workload, seed identical |
| 3 | rerun a matched pair | ✅ 3 lifecycles each side (base: 7d36ef9f, c04e4681, b2e2a7cf; head: eaa94f8b, 73d47651, ababc337) |
| 4 | check predicted phase delta appears/disappears | ✅ base median tail 41.0 s, head median tail 2.0 s |
| 5 | output reusable counterfactual template | ✅ `docs/g6_counterfactual_spec.md` |
| 6 | not blind-scored | ✅ explicitly labeled development-level |

## 2. Result

| | base (restore present) | head (restore absent) |
| --- | --- | --- |
| per-lifecycle total_s | [378.7,377.7,376.7,418.7], [378.0,376.0,377.0,417.9], [379.9,378.9,377.9,422.1] | [414.5,415.5,413.5,413.1], [428.3,427.3,429.3,426.7], [485.5,484.5,483.5,482.9] |
| recovery tail (max − median(other)) | 41.0 / 40.8 / 43.3 s | 2.0 / 2.0 / 2.0 s |
| complete seven-stage episodes | 3 (1/lifecycle), 0 loss | 0 |
| median tail | **41.0 s** | **2.0 s** |

Pass rule: base median tail > 10 s **and** head median tail < 5 s → **PASS**.

## 3. Interpretation

The predicted phase delta — the ~40 s recovery tail on the preempted-and-restored
request — **appears in base and disappears in head** when the only changed
variable is the recovery/restore mechanism. This is consistent with the H2D
restore (copy + wakeup + re-admission) being causal for that tail. It is a
development-level counterfactual; it does not establish blind-attribution
accuracy, MRR, or time-to-localize (those require the Team-A custody/reveal
protocol).

## 4. Artifacts

- `docs/g6_counterfactual_spec.md` (reusable template)
- `.benchmarks/results/g6_counterfactual_20260811/run_summary.json`
- raw runs: `/root/kv-recovery-service-g4/runs/<run_id>/` (server.log,
  pressure_client.out, trace shards)
