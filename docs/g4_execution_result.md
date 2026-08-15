# G4 Execution Result — Fixed-8-GiB Matched Modes (2026-08-10)

> Mode semantics follow the repository definition
> (`scripts/verify_g0_pinned_pair.py`, `docs/pinned_pair_scheduler_compatibility.md`):
> all three modes at **exact 8 GiB device KV**, differing only by connector/spec.
> Registry base v1.3.0. This is a mechanism/capture result for the fixed-8-GiB
> tiering state machine, not a leaderboard performance claim.

## 1. Frozen modes executed (repo-defined)

| mode | device KV | connector / spec |
| --- | --- | --- |
| `tiering_disabled` | 8 GiB | OffloadingConnector + `CPUOffloadingSpec` (repo proposal; boots) |
| `tiering_enabled` | 8 GiB | OffloadingConnector + `TieringOffloadingSpec` |
| `hbm_only_no_connector` | 8 GiB | none (`kv_transfer_config=None`) |

Common: Qwen2.5-14B-Instruct, NPU6, FP16, `max_model_len=32768`,
`gpu_memory_utilization=0.6`, `recompute_scheduler_enable=false`,
`SLO_limits_for_dynamic_batch=-1`, default scheduler, profiler scope on.

## 2. Workload (pressure profile)

4 concurrent `/v1/completions`, 15000-token prompt (seed 20260809),
`max_tokens=8192`, temperature 0, streaming. (The official 1-RPS registry
workloads are negative coverage at 8 GiB — they peak at 9–21% cache usage.)

## 3. Results (3 independent lifecycles per mode, every repetition)

| mode | lifecycle total_s (4 reqs) | median_s | IQR | preemptions | complete episodes | loss |
| --- | --- | --- | --- | --- | --- | --- |
| disabled | [385.6,386.6,384.6,384.1], [386.9,387.9,385.9,385.4], [384.3,385.3,383.3,382.8] | 385.36 | 2.29 | 3 | 0 | 0 |
| enabled (trace on) | [379.8,377.8,378.8,420.0], [379.8,378.8,377.8,419.9], [380.7,379.7,378.7,421.1] | 379.74 | 41.13 | 3 | 3 | 0 |
| enabled (trace off) | [378.5,376.5,377.5,418.6], [378.7,376.7,377.7,418.6], [380.2,378.2,379.2,420.0] | 378.62 | 40.84 | 3 | 0 | 0 |
| hbm | [385.1,386.1,384.1,383.6], [384.4,385.4,383.4,383.0], [384.8,385.8,383.8,383.3] | 384.25 | 1.88 | 2 | 0 | 0 |

Run ids: `runs/` under `/root/kv-recovery-service-g4/` (f4b1b083, 0fe82cc1,
d20f2126 = disabled; 24b0508b, adf18208, fb81d458 = enabled-on; 6a25a237,
03df5c5c, f3ebbbcd = enabled-off; c1c36a68, ed9925b8, 3d31701a = hbm).

## 4. Findings

1. **Mechanism captured**: only `tiering_enabled` produced complete
   `preempt → restore_start → restore_done → scheduler_wakeup → admission →
   first_prefill_or_decode` episodes (1 per lifecycle, 3 total, 0 loss). The
   preempted request paid a restore tail (~420 s vs ~379 s), while the other
   three requests finished faster (~378–381 s) than the disabled/hbm modes
   (~383–388 s) — the CPU tier offloads their KV and reduces their wait.
2. **Median**: enabled 379.7 s < hbm 384.3 s < disabled 385.4 s. Single
   workload, small samples — directional, not a leaderboard conclusion.
3. **Observer overhead**: tracing on vs off for `tiering_enabled` median
   379.74 vs 378.62 s (+1.1 s, ~0.3%) — negligible at this scale; both produce
   the same timing pattern.
4. **hbm (8 GiB, no connector)** saturates the same 8 GiB cache (preemptions
   0/1/1) — it is a distinct control from `tiering_disabled` (which keeps the
   OffloadingConnector + CPUOffloadingSpec machinery).

## 5. Compliance notes

- Mode definitions follow the repo; all three modes boot and run.
- ≥3 independent lifecycles per mode (requirement satisfied for this workload).
- Every repetition reported; median + IQR per mode.
- Observer overhead measured (tracing on/off, enabled mode).
- `recompute_scheduler_enable=false` and the runtime `TieringOffloadingSpec`
  are used for the profiled row; no device NPU tiering spec, no
  RecomputeScheduler.
- Workload is a documented pressure deviation from the 1-RPS registry
  workloads because those are negative coverage at 8 GiB (see finding in the
  first round); the registry workloads themselves were run and reported as
  negative coverage.

## 6. Artifacts

`/root/kv-recovery-service-g4/runs/<run_id>/`: `server.log`,
`pressure_client.out`, trace shards, `run_id.txt`. Spec:
`docs/g4_execution_spec.md`.
