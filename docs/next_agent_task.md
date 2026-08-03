# Next Agent Task: KV-Recovery Controlled Runtime Integration

## Current Gate

The assigned M0 question is blind causal localization for online regressions:
normalize request traces into a phase DAG, compare structured traces, rank
top-k mechanism candidates with confidence and unexplained residual, and test
the top prediction with a minimal rank-one counterfactual.

The minimum runtime protocol is owner-frozen in
[`../contracts/p0/owner-freeze-approval.json`](../contracts/p0/owner-freeze-approval.json).
The approved contract and taxonomy bytes still contain their original
`freeze_candidate` review labels because the approval is content-addressed;
do not edit them in place. P0 completion does not change the evidence state:
the project remains `NOT_M0_PROVEN`.

The checked-in NPU6 runs predate this blind protocol. They remain useful
development fixtures for normalizer, exporter, and regression tests, but their
causes and conclusions are already exposed and cannot contribute to primary
blind accuracy, MRR, or time-to-localize metrics.

Faculty comments `5157885904` and `5157931714` make KV recovery the immediate
P1 integration slice. Upstream profiler PR #4 is merged and supplies typed
preempt/restore/wakeup/requeue/admission/first-compute events and latency
decomposition. Remygred's next deliverable is a controlled runtime trace with
the complete request ID preserved across those stages; a tiering/HBM-only
matched experiment comes only after that trace passes its gates. The comments
do not alter the approved P0 digests or turn a BLOCKED preflight into a
performance result.

## Verified Repository State

Reverified through authenticated Git/SSH on 2026-08-03:

- local profiler-parent feature base:
  `84261a2458e1f961b0279b70780ca9497bad3f2e`;
- authenticated profiler upstream main after merged PR #4:
  `15717eae2630e80c11b113ccaeb3422871b35b40`;
- active integration branch: `feature/kv-recovery-integration`, carrying
  parent composition commits `23195eac51643369c2b8fc287bb714f9a9ddd69d`
  and `bd3950a35cb3f60918179185dd6a5d1206dace51` on that upstream base;
- pinned workload feature/gitlink:
  `76e24c85bcab76ecfabb831c9444002b6efffd58`;
- pinned historical runtime-hook feature/gitlink:
  `0daab7a300fb91efebd35b221b9a6f6c6d7486f8`;
- current vLLM-HUST main: `f229ba7cad21a4dba58681af6738a9fd947388e2`;
- current vLLM-Ascend-HUST main:
  `cafad89a5e103f31ea517c1edb56130578c3cd56`;
- current benchmark main: `0858cdb326e88ebaf8027966ba754da5ea800db4`.

The device-plugin advance from `590855422...` to `cafad89a5...` changes only
GitHub Actions setup-python versions. The benchmark advance from `12c6e131...`
to `0858cdb...` changes aggregation admission logic; the official-target
registry itself remains version `1.0.0`, hash
`2073283467797cbe4a74682249b4e40c7c5ded4ebd393392161e038dd9bdb94c`,
with nine active targets that all include the `enforce_eager` flag.

The historical runtime hook submodule is a patch reference, not the next
implementation base. The owner-frozen P1 pair is runtime
`f229ba7cad21a4dba58681af6738a9fd947388e2` plus device plugin
`cafad89a5e103f31ea517c1edb56130578c3cd56`; P1 is restricted to
`communication_mode=none`.

Committed checkpoint `9f1464b8d017ef48e66b8b4c9bd4a5a37fdc563d` remains the immutable pre-PR #4
audit point. Its controlled composition with PR #4 is complete on
`feature/kv-recovery-integration`; the only cherry-pick conflict was resolved
additively in `__init__.py`. Preserve the historical checkpoint and continue
from the integration branch. Do not repeat the sync, rebase the checkpoint, or
replace its historical hashes with integration hashes.

## Parent and PR #4 CPU Gates Completed Locally

The prescribed conda environment now exists at
`/home/shuhao/miniconda3/envs/vllm-request-lifecycle-profiler-exp` and uses
Python 3.11.15. The parent-side protocol/exporter candidate is committed at
`9f1464b8d017ef48e66b8b4c9bd4a5a37fdc563d`; its exact audited hashes and
behavior are recorded in `../AGENTS.md`.

Current local verification: focused protocol/exporter tests `58 passed`, full
suite `89 passed`, shared-workload smoke `26 supported / 2 intentional boundary
skips`, targeted Ruff passed, import and dependency checks passed, and isolated
sdist/wheel build passed. This is a parent/CPU gate only: no NPU service was
started, no runtime/device call sites were changed, and neither P1 integration
nor M0 is complete.

On the integration branch, the combined parent plus PR #4 gate passed `67`
focused tests and `94` full-suite tests plus targeted Ruff check/format. The P0
contract/taxonomy hashes and the four limited-GO runtime/test files remain
unchanged; dependency/import checks and isolated sdist/wheel packaging pass,
and affected integration hashes are recorded in `../AGENTS.md`. This is still
offline composition only: the optional profile and runtime/device call sites
are not implemented, no NPU service was started, and M0 is not proven.

## Work Now — No Hardware

1. Preserve committed parent checkpoint
   `9f1464b8d017ef48e66b8b4c9bd4a5a37fdc563d` and its hashes without amend,
   rebase, or force-push. After any source change, invalidate the affected GO
   and rerun the parent CPU gate.
2. Continue only from `feature/kv-recovery-integration`. PR #4 reconciliation,
   conflict resolution, affected digest calculation, and combined CPU/Ruff
   validation are complete. Keep the historical checkpoint section intact and
   use the separate integration checkpoint in `AGENTS.md` for current hashes.
3. Before runtime edits, freeze a versioned optional KV-recovery adapter or
   profile. It must define exact owners/boundaries for all seven stages,
   especially `admission`; complete bounded request-ID association to canonical
   `trace_id`/engine sequence; block-ID bounds; requeue-reason vocabulary;
   monotonic-ns capture and offline-ms conversion; missing/duplicate/inverted
   event handling; and profile/version provenance. Do not add
   `restore_start`, `restore_done`, or `scheduler_wakeup` to frozen
   `rlp.trace/v1alpha1` without a new contract digest and owner approval.
4. Reverify availability and compatibility of runtime
   `f229ba7cad21a4dba58681af6738a9fd947388e2` with device plugin
   `cafad89a5e103f31ea517c1edb56130578c3cd56`, then prepare only reviewed thin
   shim/call-site changes against that exact pair. Do not implement against the
   stale `0daab7a...` submodule or cherry-pick its full historical branch.
   Treat the scheduler interface as a hard check: the pinned runtime passes
   `self._should_throttle_prefills()` to `schedule()`, but the pinned device
   `RecomputeScheduler.schedule(self)` accepts no argument. If the selected
   tiering connector installs that scheduler, obtain an approved compatibility
   patch or new paired SHA and add an interface test; otherwise prove and record
   that the resolved mode uses a compatible scheduler.
5. At worker bootstrap call
   `RuntimeLifecycleHooks.reinitialize_after_fork()` explicitly. Wire the
   supported-mode gate, lifecycle state, sidecars, handoffs, terminal ordering,
   cleanup roster, and explicit causal edges without adding another exporter
   or doing file/log handler I/O in producer event paths.
   When constructing the explicit expected-shard list, consume only
   `committed_shard_path` after `close()` returns the immutable
   `drained + summary_written` receipt. The raw `shard_path`, a convenience
   glob, an empty reservation sentinel, or a valid-looking late file is never
   an admission signal. First freeze an independent expected-process roster;
   require one successful receipt for every roster member and reject the whole
   run on any missing/timeout/failure result. Never build a manifest with
   `filter(None)`.
   Carry the exact bounded external request ID, engine sequence identity, and
   stable block identities across every recovery stage. Keep
   `CLOCK_MONOTONIC` nanoseconds on wire; derive PR #4 milliseconds offline.
   Do not reconstruct joins from logs or timestamps.
   For frozen P1 `n=1`, represent sequence identity with the canonical engine
   lifecycle and `sample_index=0`; do not invent a nonexistent runtime sequence
   ID. Treat physical GPU/CPU block IDs as rank/allocator-local and reusable,
   and bind them through a scoped logical recovery-block association.
6. Run CPU runtime-integration tests with tracing disabled and enabled. Require
   one complete fake recovery episode and one valid no-pressure trace. Only
   after these pass may a read-only NPU preflight be requested. Formal blind
   scoring still waits for fresh sealed cases and target freeze.

## Minimum P1 Test Matrix

- disabled fast path and plugin absent;
- incompatible schema/API version;
- initialization, enqueue, writer, and serialization failure;
- queue saturation, exact drop accounting, and reserved terminal/loss records;
- close, bounded flush timeout, and process shutdown;
- per-process shard ownership and deterministic shard summary;
- payload/privacy bounds and rejection of unbounded metadata;
- dual start/end span IDs, cross-process queue/output sidecars, the required
  edge roster, and cycle rejection;
- current-runtime terminal ordering: core terminal, real `_free_request`
  cleanup, EngineCoreOutput handoff, then root-scope output readiness;
- max-tokens-one, local homogeneous prefix-cache hit, chunked prefill,
  preemption/resume, streaming/non-streaming, and every diagnostic-only mode;
- existing nine-event compatibility mapping without silently redefining old
  fields;
- complete seven-stage KV-recovery episode and a valid trace with no pressure
  episode;
- missing, duplicated, inverted, or cross-clock recovery milestones;
- complete request ID to `trace_id` to sequence association, over-bound or
  privacy-invalid IDs, and request/sequence drift;
- empty/changed/unbounded restore block IDs, zero/overflow moved bytes, and
  block identity drift;
- zero, one, and multiple requeues; required bounded reason; requeue count and
  order; prefill and decode resume variants;
- exact ns-to-ms decomposition for copy, restore/wakeup, wakeup/admission,
  admission/first-compute, and total recovery;
- version/profile mismatch, recovery-record overflow/loss, and whole-run
  rejection on an incomplete expected-process receipt;
- READY-to-BLOCKED and BLOCKED-to-READY marker cleanup, plus rejection when
  both or neither marker is present; and
- the pinned scheduler API interface under every proposed tiering connector.

Run project checks only in the required conda environment and isolate the
polluted shell paths:

```bash
env -u PYTHONPATH -u LD_LIBRARY_PATH \
  PYTHONNOUSERSITE=1 \
  PYTHONPATH=/root/vllm-request-lifecycle-profiler-plugin/src \
  PYTHONDONTWRITEBYTECODE=1 \
  /home/shuhao/miniconda3/envs/vllm-request-lifecycle-profiler-exp/bin/python \
  -B -m pytest -q
```

For the shared workload smoke, additionally set
`LLM_SERVING_WORKLOADS_SRC=/root/vllm-request-lifecycle-profiler-plugin/third_party/llm-serving-workloads/src`
and invoke `.benchmarks/run_shared_workloads_smoke.py` with its checked-in JSON
and Markdown outputs. For packaging, use isolated `python -m build`; do not use
`--no-isolation` because the environment's setuptools 83.0.0 is newer than the
project's declared build-backend ceiling. Do not substitute system Python.

## Performance PR Merge Gate

Before merging any performance implementation PR, official or specialty, use
the combined gate: benchmark #95 supplies canonical artifact admission, while
the alternating-run/correctness rigor is inherited from vllm-hust #185. Record
matched base/head; exact target ID/version/profile and registry/spec hash;
workload and resolved configuration; paired core/plugin SHAs; at least three
independent service lifecycles per side in alternating order; raw
request/runtime artifacts; environment manifest; `metadata.data_source`
starting with `real-online` or an explicitly allowlisted CI real-online source;
artifact-local `leaderboard_manifest.json` and `run_leaderboard.json`;
correctness gate, reported error rate, and target-specific acceptance
threshold; every repetition plus median/IQR; canonical paths/URLs; and an
explicit deviation/specialty reason. Missing, busy, skipped, cancelled,
smoke-only, replay-only, or derived-only evidence fails closed.

## Formal Evaluation Gate

Before a scored P2/P3 run, Team A must freeze and isolate:

- at least two fresh opaque positive cases and one valid
  `no_single_root_cause` or `insufficient_evidence` negative case;
- a flat-summary comparator and structured-DAG method with equal information
  and time budgets;
- critical-path share, attribution precision, top-1/top-3 accuracy, MRR,
  time-to-localize, trace overhead, cross-run variance, residual, abstention,
  and wrong-attribution severity scoring;
- one rank-one counterfactual for every non-abstained top prediction;
- exact graph-mode `specialty-target` specs and matched base/head runs.

The active official registry is eager-only, so it can be used for provenance
or eager diagnostics but not silently relabeled as formal graph-mode evidence.

## Hardware Admission

No managed server is assumed to be running. PR #4's latest recorded read-only
preflight is BLOCKED; this means environment not admitted, not poor online
performance. Before requesting NPU6, run a version-aware whole-trace preflight
that requires exactly one marker: READY with no BLOCKED marker when all checks
pass, or BLOCKED with no READY marker otherwise. On BLOCKED, stop and do not
launch a service or emit latency/throughput conclusions.

After READY, run one controlled pressure-episode smoke and verify the entire
request/sequence/block/stage chain before measuring performance. The smoke is
`real-online + smoke-only`; it does not support a speedup claim. Do not kill
unrelated processes, silently change devices, reuse a stale endpoint, or
launch from the historical hook branch.

READY is not sufficient to bypass the protocol gate: if the smoke enables a KV
connector/offload or host/device transfer, the new communication/specialty
profile and exact runtime/device compatibility must already be approved.

The first matched candidate then follows benchmark #134: fixed 8 GiB,
Qwen2.5-14B-Instruct, Ascend 910B2 x1, FP16, `max_model_len=32768`, steady 1
RPS, the same requests and resolved configuration, and mutually exclusive
tiering-disabled/tiering-enabled/HBM-only modes. Use at least three independent
service lifecycles per mode in rotating/alternating order and report every
repetition plus median/IQR. A copy-optimization on/off pair is separate and
allowed only if supported. Next expand to 8/16/24/32 GiB over random-online,
sharegpt-online, and prefix-repetition-online. Record the complete metric and
artifact set specified in `experiment_plan.md`.

Tiering/offload cannot be formal under the currently approved
local-homogeneous-KV `communication_mode=none`; acquire the versioned issue-#2
communication profile or an explicitly approved specialty profile first.
HBM-only may remain `none`. An experiment without an actual recovery episode
is negative coverage, not evidence of tiering behavior.

Historical experiment details and result paths remain in
[`experiment_plan.md`](experiment_plan.md),
[`live_fault_matrix_plan.md`](live_fault_matrix_plan.md), and
[`claim_ledger.md`](claim_ledger.md). Read them as evidence history, not as an
instruction to bypass the frozen protocol or the remaining evaluation gates.
