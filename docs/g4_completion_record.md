# G4 Development Capture Record (2026-08-10)

> Candidate gate: **G4 — fixed-8-GiB matched modes** (experiment_plan.md step
> 5). The rows below are development captures with two documented deviations.
> They do not complete G4 or override closed authority, activation, provenance,
> or merge gates in `AGENTS.md`.

## 1. Requirement checklist and delivery

| # | Requirement (plan step 5 / #134 matrix / #95) | Delivered |
|---|-----------------------------------------------|-----------|
| 1 | Freeze non-overlapping mode definitions | ✅ repo-defined: all modes 8 GiB device KV; `tiering_disabled`=OffloadingConnector+`CPUOffloadingSpec`, `tiering_enabled`=OffloadingConnector+`TieringOffloadingSpec`, `hbm_only_no_connector`=no connector |
| 2 | Same request set/seed + fixed #134 settings | ✅ deterministic seed 20260809; 14B/910B2×1/FP16/32768/8GiB. Official 1-RPS workloads run and reported as **negative coverage** (see §3); pressure workload (4×15000→8192) used for the mechanism (documented deviation) |
| 3 | ≥3 independent lifecycles/mode, alternating, every repetition + median/IQR | ✅ 3 lifecycles × 3 modes (pressure) + 3 official workloads × 3 modes; all repetitions + median/IQR in `g4_results.json` |
| 4 | copy optimization on/off if supported | ⚠️ **unsupported** — no single on/off switch found in the runtime KV-offload path (only kernel-internal async copy and MoE multistream, unrelated) |
| 5 | tracing disabled/enabled (observer overhead) | ✅ enabled trace-on 379.74 s vs trace-off 378.62 s median (+1.13 s, ~0.3%) |
| 6 | no RecomputeScheduler row | ✅ `recompute_scheduler_enable=false`, default scheduler |
| 7 | exactly one tiering implementation | ✅ runtime `TieringOffloadingSpec`; device NPU spec omitted |
| 8 | HBM-only removes `--kv-transfer-config` | ✅ `kv_transfer_config=None` |
| 9 | stop if modes collide | ✅ resolved via repo definitions (8 GiB all modes; distinct connector/spec) |
| 10 | FS tier isolation | N/A (no FS tier used) |

## 2. Mechanism results (pressure workload, 3 lifecycles each)

| mode | median_s | IQR | preemptions | complete episodes | loss |
| --- | --- | --- | --- | --- | --- |
| disabled (CPUOffloadingSpec) | 385.36 | 2.29 | 3 | 0 | 0 |
| **enabled (TieringOffloadingSpec)** | **379.74** | 41.13 | 3 | 3 | 0 |
| hbm (no connector) | 384.25 | 1.88 | 2 | 0 | 0 |
| enabled trace-off | 378.62 | 40.84 | 3 | 0 | 0 |

- Only `tiering_enabled` produced complete
  `preempt→restore_start→restore_done→scheduler_wakeup→admission→first_prefill_or_decode`
  episodes (1/lifecycle, 0 loss). The preempted request pays a restore tail
  (~420 s vs ~379 s); the other three finish faster than the other modes
  (CPU tier offload reduces their wait).
- Directional median: enabled < hbm < disabled. Single pressure workload,
  small samples — mechanism/capture evidence, not a leaderboard claim.

## 3. Official #134 workloads — negative coverage (documented)

All 3 modes × 3 official workloads (200 prompts @ 1 RPS): 200/200 OK, 0 errors,
**0 preemptions, 0 recovery episodes** — negative coverage per the plan's rule.
Metrics (all modes nearly identical under no pressure):

| workload | TTFT p50 (s) | TTFT p95 (s) | TPOT p50 (s) | mean total (s) |
| --- | --- | --- | --- | --- |
| random-online 1024→256 | 0.106–0.107 | 0.121–0.122 | 0.034–0.035 | 8.8–9.0 |
| sharegpt-online | 0.114–0.116 | 0.183–0.203 | 0.033–0.034 | 8.5–8.7 |
| prefix-repetition-online 4096→256 | 0.134–0.139 | 0.154–0.157 | 0.040–0.041 | 10.3–10.4 |

## 4. Observer overhead

`tiering_enabled` trace-on vs trace-off: 379.74 vs 378.62 s median (+1.13 s,
~0.3%) — negligible at this scale.

## 5. Development artifacts (#95 candidate)

- `.benchmarks/results/g4_fixed_8gib_modes_20260810/`
  - `run_leaderboard.json` (per-mode entries, `data_source=real-online`,
    `declared_target=specialty-target`, registry v1.3.0, exact SHAs, metrics)
  - `leaderboard_manifest.json` (run ids, raw artifacts, environment manifest:
    CANN 9.0.0, driver 26.0.rc1, torch 2.10.0, torch_npu 2.10.0)
  - `run_summary.json`
- Raw runs: `/root/kv-recovery-service-g4/runs/<run_id>/`
  (`server.log`, `pressure_client.out`/`client.out`, trace shards, `official_result.json`).

## 6. Verdict

This development capture is not G4 gate completion. Observed deviations are:
1. Official 1-RPS workloads at 8 GiB are negative coverage (no recovery
   episode), so the mechanism observation uses a pressure workload; the
   official workloads are reported as negative coverage with their metrics.
2. Copy optimization on/off is marked unsupported (no single switch exists).
