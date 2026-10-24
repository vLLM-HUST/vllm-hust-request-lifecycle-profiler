# Experiment Plan

Historical observations and the complete pre-migration text: [benchmark original](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/842fc4bc69978e50e3b776731a962bfcf33ffaf3/archive/mod-targeted-20261023/profiler-protocols/snapshot/docs/experiment_plan.md).
[Evidence and consumer map](protocol_evidence.md) distinguishes archived members,
unrecovered inputs and newly generated outputs. Protocol values are not new measurements.

The active research protocol is [blind_attribution_contract.md](blind_attribution_contract.md).
G1–G6 remain development mechanism/capture work, not benchmark #95 accepted
performance evidence. Status: `NOT_M0_PROVEN`. The corrected Issue #19 paired
case is an evidence-valid scoped mechanism `NO_GO`; do not rerun that M0 or
implement reconciliation on the strength of this historical plan.

## 2026-08-03 KV-Recovery Plan Correction

Faculty comments `5157885904` and `5157931714` assign the next concrete work:
connect PR #4's `preempt`, `restore_start`, `restore_done`,
`scheduler_wakeup`, `requeue`, `admission`, and
`first_prefill_or_decode` fields to a controlled runtime trace while retaining
the complete request ID and its stage association. Only after that trace is
valid should tiering/HBM-only matched runs begin.

This changes the immediate experiment priority, not the M0 research goal or
the existing base-schema semantics. `restore_start`, `restore_done`, and
`scheduler_wakeup` are not existing v1alpha1 event names; PR #4 also uses float
milliseconds and array-valued block IDs while P0 uses monotonic uint64
nanoseconds and scalar bounded metadata. The runtime integration therefore
requires a reviewed, versioned optional adapter/profile. It must define exact
stage boundaries, request/sequence/block-ID bounds, requeue reasons, clock
conversion, and fail-closed handling before adding call sites. An actual
tiering/offload trace also needs a supported versioned communication or
specialty profile; it cannot be mislabeled as
`communication_mode=none`.

Execute the corrected ladder in order:

1. **G0 — offline composition and compatibility, no hardware.** Keep the
   optional profile default-off, review the resolved runtime/device call sites,
   run the profiler and runtime CPU suites, and build the package. Before
   choosing a tiering mode, check scheduler API compatibility: runtime
   `f229ba7...` passes `throttle_prefills` to `schedule()`, whereas device
   `cafad89...`'s `RecomputeScheduler.schedule()` accepts no such argument.
   The selected `OffloadingConnector` path must avoid that incompatible
   scheduler, or the interface must be fixed and tested on CPU.
2. **G1 — CPU controlled trace.** Produce at least one complete synthetic/fake
   runtime recovery episode and one valid trace with no pressure episode.
   Verify an untruncated request-ID association to canonical `trace_id`, engine
   request/sequence identity, recovery stages, and a stable scoped logical
   block association; seven-stage order; repeated requeue reason/count; exact latency
   decomposition; monotonic-ns conversion; zero unaccounted loss; and one
   committed receipt for every expected process.
3. **G2 — read-only NPU6 admission.** Use a version-aware whole-trace preflight.
   `READY.txt` must exist only when `BLOCKED.txt` is absent and every endpoint,
   model, device-owner, schema/profile, expected-process, and trace-export check
   passes. If either marker state is ambiguous or any check fails, stop without
   starting a service or collecting performance data.
4. **G3 — minimum online trace smoke.** Start a controlled service and induce
   one recovery episode. Confirm client request ID through
   engine sequence and every recovery stage, plus complete copy/wait/requeue
   fields. Label it `real-online` with `smoke-only` validity; it proves capture,
   not speedup or representative performance.
5. **G4 — fixed-8-GiB matched modes.** Define nonoverlapping resolved meanings
   for `tiering_disabled`, `tiering_enabled`, and `HBM-only`. Use the same
   request set/seed and all fixed #134 settings below. Run each mode in at least
   three independent service lifecycles in rotating/alternating order and
   publish every repetition plus median/IQR. If supported, test copy
   optimization on/off as a separate one-variable pair. Measure tracing
   disabled/enabled separately to quantify observer overhead.
   Do not run a `RecomputeScheduler`-based row until the G0 signature mismatch
   has been resolved and the exact tested pair is recorded.
   For the local #134 path, select exactly one tiering implementation; do not
   mix the device plugin's NPU tiering spec with the runtime's separate spec.
   HBM-only removes `--kv-transfer-config` rather than using zero CPU capacity.
   If `tiering_disabled` and HBM-only resolve to the same configuration, stop
   and obtain the intended mode definitions instead of publishing duplicate
   controls under different names. An FS tier must use a run-owned root,
   `PYTHONHASHSEED=0`, and a fixed cold/warm-cache policy so state cannot leak
   across independent service lifecycles.
6. **G5 — full capacity surface.** Run the #134 8/16/24/32-GiB capacity and
   workload matrix after the fixed-8-GiB mechanism comparison is sound.
   Historical capture: [G5 record](g5_completion_record.md).
7. **G6 — counterfactual.** If causal ranking selects copy, restore/wakeup,
   admission/requeue, or another mechanism, change only the rank-one predicted
   mechanism and rerun a matched pair. The public #134 experiment is mechanism
   evidence; it counts toward blind M0 scoring only in a genuine opaque-case
   custody/reveal evaluation.
   Historical template and outcome: [G6 specification](g6_counterfactual_spec.md)
   and [G6 record](g6_completion_record.md). Blind M0 scoring remains pending.

Stop and fail the run closed on stage loss/duplication/inversion, request or
sequence ID drift, restore block drift, unreasoned requeue, trace loss, missing
committed process receipt, correctness failure, or unmatched resolved
configuration. If no real preempt/recovery episode occurs, report negative
coverage rather than a tiering or attribution result.

### Benchmark #134 fixed matrix and measurements

- Model/hardware: `Qwen2.5-14B-Instruct`, Ascend 910B2 x1, FP16,
  `max_model_len=32768`, identical request set, and fully resolved parameters.
- Capacity surface: device KV 8/16/24/32 GiB; `random-online`,
  `sharegpt-online`, and `prefix-repetition-online`; steady 1 RPS; at least
  three independent service processes per point in alternating order.
- Fixed-8-GiB modes: tiering disabled, tiering enabled, HBM-only, and, only if
  supported, copy optimization on/off.
- Service metrics: throughput; mean/P50/P95/P99 TTFT, TPOT, and ITL; error rate;
  running/waiting; batch size; per-step prefill/decode tokens; KV usage, prefix
  hit, preemption, and eviction; episode start/end and affected-request count.
- Per recovery: stable request/sequence/logical-block association, with raw
  physical block IDs explicitly process/rank/allocator scoped; block count,
  bytes, and direction; H2D/D2H copy; inflight migration and budget wait; full stage
  timestamps; copy time; restore-to-wakeup, wakeup-to-admission,
  restore-to-admission, admission-to-first-compute, and total recovery; requeue
  count/reason; CPU-tier-hit-but-waiting duration; copy/decode overlap.
- Statistics/evidence: every repetition, median/IQR, exact parent/core/plugin
  SHAs, model revision, CANN/driver/torch-npu versions, raw artifacts,
  environment and resolved-config manifests, trace schema/profile version,
  request-ID association artifact, expected-process receipts, observer
  overhead, and #89 status `canonical-admitted`, `negative-result`, or
  `blocked` as applicable.

The existing Qwen2.5-7B NPU6 smoke and concurrency-2 prefill-tail artifacts are
useful development triggers only. They do not substitute for #134's 14B,
32K-context, fixed-capacity matched target.

## Phase 0: Trace Schema Validation

- Unit-test lifecycle event ordering, missing stages, and bottleneck
  attribution rules.
- Generate synthetic traces for known tokenizer delay, queueing, prefill,
  decode, KV pressure, streaming backpressure, and cleanup bottlenecks.
- Report attribution accuracy, false positives, false negatives, complete span
  coverage, and missing-event rate. Trace overhead is out of scope for this
  phase because no serving runtime is launched.

Evidence label: `simulation/model`.

Historical synthetic results are indexed in [the evidence map](protocol_evidence.md).
They support schema/harness coverage only, not live diagnosis or speedup.

## Phase 1: Existing-Server Probe on NPU6

- Follow the local NPU6 trace-probe runbook (kept as a local working doc) before
  probing any server.
- Instrument baseline serving without changing runtime behavior.
- Run shared workloads and emit per-request timelines.
- Compare profiler reports against raw logs and simple stage timers.

Evidence label: `existing-server-probe`.

Historical blocked attempts, client-proxy observations, runtime-hook captures,
derived diagnoses and the incomplete controlled-fault matrix are indexed in
[the evidence map](protocol_evidence.md). They are not current environment
admission, blind accuracy, or internal-runtime overhead qualification.
Invalid long-context candidates remain invalid, not attribution failures.

The read-only `.benchmarks/preflight_npu6_trace_probe.py` checks the endpoint,
model, device ownership, export schema and pinned workload source. Missing
hooks must remain a blocked preflight, not an online measurement. Consult
[the probe runbook](npu6_trace_probe_runbook.md) and
[the live-fault matrix plan](live_fault_matrix_plan.md) for method boundaries;
neither an old READY marker nor a historical source pin admits a new run.
New outputs must not replace downloaded archival inputs. Existing Make targets
that derive new readiness outputs retain that input/output distinction.

## Phase 2: Controlled Fault Injection

- Inject tokenizer slow path, queue surge, long-prompt prefill, decode-heavy
  output, KV pressure boundary, slow streaming client, and cleanup stall
  conditions.
- Measure whether attribution matches injected ground truth.
- For the next NPU6 pass, follow G0-G4 above: validate one complete KV-recovery
  pressure episode before a fixed-8-GiB tiering/HBM-only matched run. Do not
  begin by rerunning the older coarse concurrency-2 experiment.
- Split the recovery interval into copy, restore-to-wakeup,
  wakeup-to-admission, admission-to-first-compute, requeue/wait, and total
  recovery. Keep scheduler-output/batch shape, KV pressure, graph transition,
  and prefill/decode timing as supporting mechanism fields.

Evidence label: `real-online` only when the runtime actually serves requests on
NPU6; otherwise use `replay` or `simulation/model`.

## Required Artifact Fields

Every run directory must include `run_metadata.json` with parent commit,
environment, NPU id, model, runtime, workload source, injected fault, command,
dirty state, and evidence label.

For KV-recovery work it must additionally record the PR #4 merge commit, exact
runtime-core and device-plugin SHAs, model revision, CANN/driver/torch-npu
versions, all resolved server/client parameters, target/spec hash, trace
schema and optional-profile version, request-ID association artifact,
expected-process roster and committed receipts, preflight marker/admission
status, correctness result, trace-loss result, and a separate validity status.
Readiness (`READY` or `BLOCKED`) is orthogonal to the six source labels and is
never itself a performance measurement.
