# G3 Completion Record (2026-08-09/10)

> Gate: **G3 — minimum online trace smoke** (experiment_plan.md step 4).
> Verdict: **PASS** — two complete seven-stage recovery episodes on a live
> controlled service, zero trace loss, clean drain, labeled
> `real-online` + `smoke-only`.

## 1. Requirement checklist (what G3 required)

| # | Requirement | Delivered |
|---|-------------|-----------|
| R1 | Start a controlled online service with a fully resolved config | ✅ recorded in `run_metadata.json` |
| R2 | Induce at least one real preemption + H2D restore | ✅ `total_preemptions=2`, H2D cpu→device 1.5 GiB each |
| R3 | Request ID association through engine sequence and every recovery stage | ✅ 2 complete chains, identical request_id/episode_id/epoch per chain |
| R4 | Complete copy/wait/requeue fields | ✅ transfer_id / 64-hex block_set_id / bytes_moved; no requeue this run |
| R5 | Per-process committed receipts (`api_server`, `engine_core`) | ✅ both shards `close_outcome=drained` |
| R6 | Live endpoint check | ✅ `GET /v1/models` 200, `max_model_len=32768` |
| R7 | Label `real-online` + `smoke-only` | ✅ in verification metadata |
| R8 | No negative-coverage episode (≥1 complete episode) | ✅ 2 complete episodes |
| R9 | Clean drain shutdown | ✅ all process shards drained |
| R10 | Zero trace loss | ✅ `loss_intervals=0`, `dropped_data=0` |

## 2. Root cause fixed this gate

The live Ascend V1 runner is `NPUModelRunner` (vllm-ascend
`vllm_ascend/worker/model_runner_v1.py`), which **overrides `execute_model`**
but did not call `observe_kv_recovery_first_compute` before `_model_forward`.
The scheduler emitted the compute context and the worker received it, but the
worker-side `first_compute` child observation never fired, so
`first_prefill_or_decode` was missing and each run recorded
`missing_first_compute_observation` losses.

Fix (device-plugin, +6 lines): call
`self.observe_kv_recovery_first_compute(scheduler_output)` inside the
`maybe_get_kv_connector_output(...)` context immediately before
`_model_forward`, mirroring the base V1 runner
(`vllm/v1/worker/gpu_model_runner.py:4381`).

## 3. Verification run

- run_id: `a270b1753b75ff80f8adc63cf91fae0f`
- Service: Qwen2.5-Coder-14B-Instruct on NPU6, `gpu_memory_utilization=0.6`,
  `max_model_len=32768`, `OffloadingConnector` +
  `TieringOffloadingSpec` (`cpu_bytes_to_use=8GiB`),
  `recompute_scheduler_enable=false`, `kv_recovery_profile_enabled=true`.
- Workload: 3 concurrent `/v1/completions`, 15000-token prompt,
  `max_tokens=8192`, temperature 0; all 3 returned 200.
- Chains:
  - `cmpl-b5eea42347bc7819-0-a3184991`: preempt → restore_start → restore_done
    → scheduler_wakeup → admission → first_prefill_or_decode
  - `cmpl-af23effcf44e71b7-0-b58ba053`: same complete chain
- Shard summary: recovery 12, transfer 28, block_set_chunk 16, wait_set 0,
  loss 0, dropped 0, `close_outcome=drained`.

## 4. Artifacts

- `.benchmarks/results/g3_minimum_online_trace_smoke_20260809/`
  - `g3_verification.json` / `g3_verification.md` (R1–R10, all ok)
  - `run_metadata.json`
  - `recovery_episode/` (engine-core shard + base trace)
  - `raw/` (server.log, client.out, api-server shard, run_id.txt)

## 5. Conclusions

1. Capture path proven on the real online service: the full seven-stage
   recovery chain, request-ID association, and copy fields are recorded with
   zero loss. The missing `first_prefill_or_decode` was a wiring gap in the
   Ascend `NPUModelRunner.execute_model` override, not a protocol/ABI defect.
2. This is capture evidence (`smoke-only`), not a tiering/HBM performance
   claim. Performance conclusions are deferred to G4+ matched runs.
3. The protocol's fail-closed behavior works as designed: abandoned episodes
   (a request re-preempted or finishing mid-recovery) are recorded as
   `loss_interval` and fail the run closed. G4 matching must use scheduling
   that avoids such abandonment.
4. Code hygiene: temporary WARNING diagnostics were downgraded to
   `logger.debug`; no debug instrumentation remains; profiler 21 passed
   (incl. cross-repo integration), runtime KV 82 passed.

## 6. Known limitation / note

- G3 smoke used `Qwen2.5-Coder-14B-Instruct` (the model available on the
  G1–G3 NPU path). The #134 official target is `Qwen/Qwen2.5-14B-Instruct`;
  that model is present in the local HF cache (28 GiB) and must be used for
  the G4 matched runs.
- One `test_scheduler.py` SWA/Eagle batch (13 failures) is pre-existing and
  unrelated to this gate (file untouched).
