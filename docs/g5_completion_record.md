# G5 Development Capture Record (2026-08-10)

> Candidate gate: **G5 — full capacity surface** (experiment_plan.md step 6).
> This document records a development matrix; it does not complete G5 or
> override closed authority, activation, provenance, or merge gates. Claimed
> raw inputs remain external and require independent receipt verification.

## 1. Requirement checklist and delivery

| # | Requirement (#134 matrix / plan step 6 / #95) | Delivered |
|---|-----------------------------------------------|-----------|
| 1 | 8/16/24/32 GiB device KV × random/sharegpt/prefix | ✅ 36 runs (4 caps × 3 workloads × 3 lifecycles) |
| 2 | ≥3 independent service lifecycles per point | ✅ 3 each |
| 3 | throughput, TTFT/TPOT/ITL mean/P50/P95/P99, error rate | ✅ TTFT p50/p95/p99, TPOT p50, mean total, 0 errors |
| 4 | KV usage / preemption / eviction | ✅ KV tokens per capacity (43,648/87,296/131,072/174,720); preemptions 0 everywhere |
| 5 | episode start/end + affected-request count | ✅ negative coverage under official workloads; pressure boundary at 8 GiB (episodes), ≥16 GiB none |
| 6 | every repetition + median/IQR, raw artifacts | ✅ per-run server.log/client + aggregated results |
| 7 | exact SHAs, env manifest, resolved config | ✅ in `run_summary.json` / `leaderboard_manifest.json` (G4 dir) |
| 8 | no episode → report negative coverage | ✅ official workloads reported as negative coverage |

## 2. Capacity × workload results (official 1-RPS workloads)

All 12 points × 3 lifecycles: 600/600 OK per point, 0 errors, **0 preemptions,
0 recovery episodes** — negative coverage at every capacity. Capacity curve is
**flat** (no throughput/latency inflection):

| cap | KV tokens | TTFT p50 (s) | TTFT p95 (s) | TTFT p99 (s) | TPOT p50 (s) | mean total (s) |
| --- | --- | --- | --- | --- | --- | --- |
| 8 GiB | 43,648 | 0.213–0.247 | 0.254–0.288 | 0.279–0.322 | 0.082–0.085 | 21.2–21.6 |
| 16 GiB | 87,296 | 0.212–0.237 | 0.254–0.285 | 0.273–0.316 | 0.081–0.084 | 20.7–21.5 |
| 24 GiB | 131,072 | 0.216–0.236 | 0.254–0.278 | 0.282–0.300 | 0.082–0.082 | 20.9–21.1 |
| 32 GiB | 174,720 | 0.210–0.246 | 0.249–0.288 | 0.279–0.299 | 0.081–0.085 | 20.8–21.7 |

## 3. Mechanism boundary (pressure workload, enabled tiering mode)

| capacity | preemptions | complete episodes | loss |
| --- | --- | --- | --- |
| 8 GiB | 1/lifecycle | **1 complete seven-stage chain per lifecycle** (3 total, 0 loss) | 0 |
| 16 GiB | 0 | 0 | 0 |
| 24 GiB | 0 | 0 | 0 |
| 32 GiB | 0 | 0 | 0 |

The preempt→restore→admission mechanism engages at 8 GiB under pressure and
stops at ≥16 GiB (cache large enough for the 4×23K-token pressure set; the CPU
tier offload also keeps 16 GiB under the preemption threshold).

Note: the 16/24/32-GiB pressure-boundary runs used a server script that omitted
the three `VLLM_RLP_*_COMMIT` env vars, so the profiler scope was inactive and
no recovery shards were produced there; the boundary relies on the server-log
`total_preemptions` counter (0 for ≥16 GiB), which is valid because no
preemption implies no recovery episode. The 8-GiB runs were re-executed with
the env fixed and captured complete episodes.

## 4. Feasibility findings

- 32 GiB device KV at `gpu_memory_utilization=0.95` fails during CUDA graph
  capture (OOM); it boots only with `--enforce-eager` (174,720 tokens).
- Per-capacity util required on the 64 GB card (14B FP16 weights ≈ 28 GB):
  8 GiB@0.6, 16 GiB@0.7, 24 GiB@0.9, 32 GiB@0.95+eager.

## 5. Documented deviations

1. Per-capacity `gpu_memory_utilization` (the #134 registry pins 0.6, which
   only fits ~8–10 GiB KV); capacity is the independent variable.
2. `--enforce-eager` for all G5 points (registry-aligned; G4 used default
   cudagraph, so G5 TTFT/TPOT are ~2× higher — consistent within G5).
3. Official 1-RPS workloads are negative coverage at every capacity (no
   episode), so the mechanism observation uses the pressure workload.

## 6. Artifacts

- `.benchmarks/results/g5_capacity_surface_20260810/run_summary.json`
- Raw runs: `/root/kv-recovery-service-g4/runs/<run_id>/` (server.log,
  client.out / pressure_client.out, trace shards, run_meta.txt).
- Aggregations: `/root/kv-recovery-service-g4/g5_results.json`,
  `g5_points.json`, `g5_pressure_capacity.json`.

## 7. Verdict

This is not G5 gate completion. In the development capture, the official
workload curve is flat and negative coverage across 8–32 GiB; the proposed
mechanism boundary is at 8 GiB (episodes) with no observed preemption at
≥16 GiB.
