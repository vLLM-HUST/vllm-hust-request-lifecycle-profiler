# Agent Instructions: Request-Lifecycle Profiler

These instructions apply to the whole parent repository. They are durable
working memory for Remygred's request-lifecycle profiling assignment. The
short lowercase `agent.md` is a compatibility handoff; this file is the
authoritative agent entry point.

## Mission and current gate

Build an optional, bounded, fail-open request-lifecycle profiler that can
normalize queue, admission, prefill, decode, communication, serialization,
delivery, and cleanup into a causal DAG, compare matched traces, rank likely
causes, and validate non-abstained top predictions with counterfactuals.

The minimum P0 runtime protocol was owner-frozen on 2026-08-02; the durable
decision is `contracts/p0/owner-freeze-approval.json`. The approved minimum
runtime contract SHA-256 is
`122963930919073179d4844422d21e85da3a522def3ace723eb992eac43cdade`
and the approved phase taxonomy SHA-256 is
`82aae94c5d124b846f77684e239714d51791115608e786079c4ea4bd4ca05abd`.
The P1 parent exporter and CPU contract candidate is implemented locally and
has passed its CPU and two-path independent review gate under the exact audit
boundary below. Two faculty comments on 2026-08-02 narrowed the immediate
implementation order to **KV-recovery profile freeze, controlled runtime-trace
integration, then matched tiering/HBM-only experiments**. This does not make
P1 or M0 complete and does not authorize a silent edit to the frozen protocol.
Do not edit either digest-bound file in place; create a new version, digest,
and owner approval for any protocol change.

Never describe the checked-in historical traces, protocol drafts, synthetic
fixtures, or local smoke results as `M0_PROVEN`.

## Authoritative sources and ownership

- Private assignment: `intellistream/vllm-request-lifecycle-profiler-plugin#1`,
  assignment comment `5141244636`, followed by KV-recovery comments
  `5157885904` and `5157931714`.
- Merged profiler implementation source:
  `intellistream/vllm-request-lifecycle-profiler-plugin#4`, merge commit
  `15717eae2630e80c11b113ccaeb3422871b35b40`.
- KV capacity and recovery-state-machine experiment contract:
  `vLLM-HUST/vllm-hust-benchmark#134`.
- Tiering evidence-policy context: `vLLM-HUST/vllm-hust-benchmark#89`.
- Migrated research source: `vLLM-HUST/vllm-hust#185`.
- Performance-target policy provenance: `vLLM-HUST/vllm-hust#193`.
- Canonical performance merge gate: `vLLM-HUST/vllm-hust-benchmark#95`.
- Official fixed-target registry contract:
  `vLLM-HUST/vllm-hust-benchmark#104`.
- Communication/synchronization evidence taxonomy:
  `intellistream/vllm-request-lifecycle-profiler-plugin#2`, owned by Luqhhh.

Issue bodies and comments must be reread through authenticated GitHub access
before changing a contract derived from them. Do not treat an old local note,
closed migration issue, or exposed retrospective case as newer authority.

Remygred owns phase normalization, structured trace differencing,
critical-path causal ranking, counterfactual evaluation, confidence,
unexplained residual, and abstention. Consume the versioned communication
taxonomy from issue #2; do not duplicate it. Reproduction owners and Team A
prepare or rotate opaque cases. Do not duplicate their underlying optimization
or root-cause task merely to construct profiler evidence.

## Repository and base discipline

- The feature branch's historical parent baseline is
  `84261a2458e1f961b0279b70780ca9497bad3f2e`. Its committed P0/P1 checkpoint is
  `9f1464b8d017ef48e66b8b4c9bd4a5a37fdc563d`. PR #4 integration was based on
  upstream `main` at
  `15717eae2630e80c11b113ccaeb3422871b35b40`. After Draft PR #5 was opened,
  authenticated remote `main` and fetched `origin/main` advanced through
  merged PR #3 to `7e10622eb5755e1af544546e93e3f63a91214ffc`, then merged
  Draft PR #5 at `a27794afa9f3fba11c6da17f06df7ed41e6fee3f` on 2026-08-03.
  PR #5's exact head is the local branch base
  `06c8fa96ff056d3326d79b2756b106af7f916749`; the merge commit adds history,
  not missing PR-#5 content. PR #3 adds only
  `docs/idle_evidence_contract.md`. Do not rewrite the immutable checkpoints
  or silently rebase this branch because remote `main` moved.
- Its pinned workload gitlink is
  `76e24c85bcab76ecfabb831c9444002b6efffd58`.
- Its pinned vLLM gitlink is
  `0daab7a300fb91efebd35b221b9a6f6c6d7486f8` and is a historical prototype
  reference, not the P1 implementation base.
- The audited current runtime main for P1 is
  `f229ba7cad21a4dba58681af6738a9fd947388e2`.
- The audited current device-plugin main is
  `cafad89a5e103f31ea517c1edb56130578c3cd56`.
- The audited benchmark snapshot is
  `0858cdb326e88ebaf8027966ba754da5ea800db4`; its active registry bytes have
  SHA-256 `2073283467797cbe4a74682249b4e40c7c5ded4ebd393392161e038dd9bdb94c`.

The owner approved the exact runtime/device pair above as the P1 base. Reverify
that both commits remain available and revalidate their technical compatibility
before integration or an evidence run; a newer `main` tip does not silently
replace the frozen pair. Use the parent gitlinks for reproducible history and
do not implement against the stale vLLM submodule.

Preserve unrelated user changes. Do not commit, push, open a PR, comment, or
alter remote state without explicit authorization.

The audited P1 candidate remains preserved by checkpoint commit
`9f1464b8d017ef48e66b8b4c9bd4a5a37fdc563d`; do not amend, rebase, or
force-push it. PR #4 was composed with that checkpoint in a separate worktree
and branch based on verified upstream `main`. Continue new work only from the
integration branch described below, unless an owner explicitly chooses a new
base. Do not repeat the reconciliation or replace the historical checkpoint.

## KV-recovery assignment update (2026-08-03)

Profiler PR #4 is merged upstream and present on the integration branch. It
adds an optional pressure-episode model alongside the base lifecycle trace,
with these stages:

- `preempt`;
- `restore_start` and `restore_done`;
- `scheduler_wakeup`;
- zero or more `requeue` observations;
- `admission`; and
- `first_prefill_or_decode`.

Its decomposition records `copy_ms`, `restore_to_wakeup_ms`,
`wakeup_to_admission_ms`, `restore_to_admission_ms`,
`admission_to_first_compute_ms`, `total_recovery_ms`, block/byte counts, and
requeue count/reasons. The model requires one stable request/sequence identity,
unique non-requeue milestones, causal stage order, nonempty stable restore
block IDs, positive moved bytes, and a reason for every requeue.

The PR #4 checkpoint is offline-only: its reported 40 tests and targeted Ruff
gate passed, but its NPU6 read-only preflight produced `BLOCKED`, did not launch
a service, and is not an online-performance result. `READY.txt` and
`BLOCKED.txt` must be mutually exclusive; a blocked artifact must state that it
is invalid for paper claims. Historical READY and online probe directories in
this repository are separate earlier evidence and must not be presented as the
PR #4 preflight outcome.

The faculty-assigned next deliverable is to connect these fields to a
controlled runtime trace while preserving the complete request ID and its
stage association. Apply all of these rules:

- Keep the approved `rlp.trace/v1alpha1` files and hashes unchanged. PR #4's
  typed Python model does not itself amend that wire contract.
- Define and obtain review for an optional, versioned KV-recovery adapter or
  profile before runtime instrumentation. Freeze stage owners/boundaries,
  especially whether `admission` means selection start or completed
  post-preemption admission; do not guess from timestamps.
- Reuse the base DAG where semantics match: PR `preempt` corresponds to base
  `preempted`; a final compute boundary corresponds to the actual
  `prefill_started` or `decode_started`. Map PR `requeue` to base `requeued`
  only for the scheduler-owned new-epoch boundary. A proposed PR `admission`
  mapping must distinguish base `admission_started` from post-preemption
  `resumed` and be frozen before use.
- Do not inject `restore_start`, `restore_done`, or `scheduler_wakeup` as
  unapproved v1alpha1 event names. `block_ids` is an array, PR #4's
  `timestamp_ms` is a float, and `sequence_id` has no v1alpha1 first-class
  field, so none can be silently placed into the current scalar metadata
  contract.
- Capture runtime ordering with uint64 `CLOCK_MONOTONIC` nanoseconds and the
  frozen clock-domain ID. Convert to PR #4 millisecond floats only during
  offline decomposition; never order events by wall-clock or log time.
- Preserve the full runtime request ID without hashing, truncating, or parsing
  it, but keep `trace_id` and `lifecycle_id` as the canonical DAG join keys.
  Under the existing P0 rule the external ID may appear only after privacy
  review as bounded noncanonical metadata (printable ASCII, at most 128
  bytes). If a real ID exceeds the approved bound, fail the evidence closed or
  approve a new profile; never truncate silently. Do not export prompts,
  tokens, auth data, client addresses, or model output.
- Give `sequence_id`, every block identity, and requeue reason explicit bounds
  and privacy semantics in the new profile. Preserve their exact association
  across every stage. Reject missing, duplicate, inverted, ID-drifting,
  block-drifting, or unexplained requeue episodes rather than reconstructing
  them from log order.
- Extend the existing bounded hook/sink path or use a strict offline adapter;
  do not create a competing exporter. Any change to the audited parent bytes
  invalidates the affected hash/GO and requires the CPU gates and reviews to be
  rerun.

The previously approved P1 pair remains runtime
`f229ba7cad21a4dba58681af6738a9fd947388e2`, device plugin
`cafad89a5e103f31ea517c1edb56130578c3cd56`, with
`communication_mode=none`; neither new comment replaces those pins. HBM-only
can stay in that mode. A tiering/offload row records H2D/D2H transfer and is
outside the frozen local-homogeneous-KV/`communication_mode=none` support
boundary. It therefore needs the versioned issue-#2 communication profile or
an explicit approved specialty profile before it can be admitted as a formal
P1 trace. Do not label an actual tiering run as `communication_mode=none` merely
to pass validation.

The exact pinned pair also has a statically verified scheduler-API hazard that
must be resolved before selecting the #134 tiering implementation. Runtime
`f229ba7...` calls `self.scheduler.schedule(self._should_throttle_prefills())`
at `vllm/v1/engine/core.py` lines 495 and 552, while device-plugin
`cafad89a...` defines `RecomputeScheduler.schedule(self)` without that
argument at `vllm_ascend/core/recompute_scheduler.py` line 192. A mode that
installs this scheduler is expected to raise `TypeError` on the first schedule.
Before hardware work, either prove that the resolved #134 offload mode uses a
different compatible scheduler, or review and approve a compatibility patch
or a new paired SHA. Add an interface-level CPU test and startup smoke; do not
discover this incompatibility during a measured run or silently change one
side of the owner-frozen pair.

### KV-recovery runtime call-site semantics

Use explicit runtime state and connector handoffs at the pinned SHAs; do not
infer any of these boundaries from nearby log lines or timestamps:

- `Request.request_id` is stable inside the engine and is the complete external
  association requested by faculty, subject to the profile's privacy/bounds.
  In the frozen P1 `n=1` path there is no independent runtime sequence ID: use
  the canonical engine lifecycle with `sample_index=0` as sequence identity and
  do not invent another engine ID. Record a recovery epoch derived from
  `Request.num_preemptions + 1` before preemption.
- Observe the preempt decision in device
  `core/recompute_scheduler.py` before `_preempt_request()`, while request ID,
  old computed-token count, and allocated block mapping still exist. Emit base
  `preempted` for the closing execution epoch only after the decision is
  accepted. The real requeue boundary is the completed `_preempt_request()`
  state transition to `PREEMPTED` and `waiting.prepend_request()`.
- D2H store metadata identifies the connector event and GPU/CPU block mapping;
  the actual worker call uses synchronization. Measure that host-observed span
  as a blocking transfer interval unless a device timing event separately
  proves pure copy duration. Do not add a new device synchronization merely for
  tracing.
- `scheduler_wakeup` is the first waiting traversal that observes the recovery
  state as ready and returns a positive external hit. Repeated peeks while the
  state is not ready are waiting observations, not repeated wakeups.
- HBM allocation and `update_state_after_alloc()` construct the H2D mapping,
  after which the request may still be `WAITING_FOR_REMOTE_KVS`. This is not
  yet base `resumed` and must not be called completed admission.
- H2D restore completion is established by the connector load-event handoff
  and scheduler `finished_recving` path. Only the later transition into
  `scheduled_resumed_reqs` and `RUNNING` is the base `resumed` boundary.
- A batch-level model-forward timestamp is not automatically a request-level
  `first_prefill_or_decode`. Prove membership from the scheduler-output request
  roster plus the explicit load-event handoff, and attach a child span/edge.
- Connector event IDs are process-local and can be shared across ranks. GPU and
  CPU block numbers are allocator/rank-local and may be reused. Freeze a
  bounded logical recovery-block association carrying process UUID, rank,
  tier/direction, and transfer identity; never present raw block numbers as
  globally stable or cross-run canonical IDs.

Keep two implementation families separate. Benchmark #134's local tiering
candidate uses an `OffloadingConnector`/`kv_both` path and must freeze exactly
one implementation (device `NPUTieringOffloadingSpec` versus the runtime's
separate tiering spec); its HBM-only control removes the KV transfer config
entirely. A PD `RecomputeCPUOffloadConnector` experiment is a different
topology and selects `RecomputeScheduler`; it hits the pinned-pair signature
hazard above. Do not mix their configurations or evidence. Both include
connector/offload transfers and therefore require a profile beyond
`communication_mode=none`.

## PR #4 integration checkpoint (2026-08-03)

Branch `feature/kv-recovery-integration` starts from upstream merge commit
`15717eae2630e80c11b113ccaeb3422871b35b40` and composes the frozen parent
checkpoint as two commits:

- `23195eac51643369c2b8fc287bb714f9a9ddd69d`: P0 protocol and bounded parent
  exporter; and
- `bd3950a35cb3f60918179185dd6a5d1206dace51`: experiment gates and durable
  documentation.

The only cherry-pick conflict was
`src/vllm_request_lifecycle_profiler/__init__.py`. It was resolved additively
so both PR #4 KV-recovery exports and the frozen runtime protocol/exporter
exports remain public. PR #4's preflight and tests were mechanically formatted
for the repository's current Ruff configuration; no runtime or device-plugin
call site was changed.

The combined offline CPU gate passed:

- focused parent plus PR #4 tests: 67 passed;
- complete repository unit suite: 94 passed;
- targeted Ruff check and format check: passed;
- dependency/import checks and an isolated sdist/wheel build passed, with
  `kv_recovery.py` present in both artifacts;
- the approved P0 contract and taxonomy SHA-256 values remain unchanged; and
- `runtime_hooks.py`, `runtime_protocol.py`, `test_runtime_hooks.py`, and
  `test_runtime_protocol.py` remain byte-identical to the limited two-review
  GO boundary recorded below.

Affected integration SHA-256 values are:

- `__init__.py`:
  `623f9e2e2ae43f4dde0729f962d7866a7ddea6cfd69af613d967ab50a0ca3209`;
- `kv_recovery.py`:
  `9b533e1620d4e282ed33eadcf8f27bb63a71cab5bfe0a6140823d9bb3d6b9849`;
- `test_kv_recovery.py`:
  `90f0f65ce1b1cde7e43e228e45950281eb307b1be1be0b642fbce6d49708c01a`;
- `test_npu6_preflight.py`:
  `8bbf37214240344a1560c7f2f729ea43edb9bb8c155a9c6e7dc1410738cfedc6`;
  and
- `.benchmarks/preflight_npu6_trace_probe.py`:
  `fbf699c4d1e7063dda48d346031c6a7738612fbebb94bd8a7b80f497c59bd8c4`.

This checkpoint proves offline composition and CPU compatibility only. It
does not freeze the optional KV-recovery profile, integrate runtime/device
call sites, admit NPU6, produce a controlled recovery trace, or prove a
performance result. Those remain the next gates.

## Active execution plan after PR #4 composition (2026-08-03)

Draft PR #5 ends the PR #4 offline-composition slice at
`06c8fa96ff056d3326d79b2756b106af7f916749`. Keep that PR focused and in Draft
until reviewed; do not append the next profile/runtime slice to its branch.
Follow-on work starts locally from that commit on
`feature/kv-recovery-profile-v1alpha1`. Creating this branch does not authorize
a push, review request, merge, issue comment, runtime edit, or hardware run.

Execute the remaining work in this order. A later gate never compensates for
a failed or unapproved earlier gate.

### G0 — profile freeze and pinned-pair compatibility (no hardware)

1. Reread the authoritative issue comments with authenticated access before
   changing a contract derived from them. Treat the frozen P0 bytes as inputs,
   not edit targets.
2. Produce a versioned optional KV-recovery profile draft plus an exact
   runtime/device call-site map. The draft must specify all seven stage owners
   and boundaries, the base-DAG mapping, request/sequence/recovery/block and
   transfer identities, clock conversion, privacy/capacity limits, requeue
   reasons, completeness rules, and fail-closed rejection behavior.
3. Keep the proposed profile separate from `rlp.trace/v1alpha1`. It may adapt
   a validated recovery episode into PR #4's typed offline model, but it may
   not silently add event names, arrays, floats, or sequence fields to the
   frozen wire contract. Record a new profile ID, exact digest, dependency
   versions, review state, and an owner-approval candidate.
4. Consume, rather than duplicate, issue #2's communication taxonomy. Freeze
   the recovery-side profile with Remygred first, then create a separate
   content-addressed specialty mapping that binds that digest and closes the
   H2D, D2H, and transfer-wait span/edge roster. It needs issue-2-owner or
   explicitly delegated authority approval. HBM-only may retain
   `communication_mode=none`; any tiering/offload candidate with D2H/H2D or
   synchronization remains blocked until both approval records exist.
5. Revalidate runtime
   `f229ba7cad21a4dba58681af6738a9fd947388e2` and device plugin
   `cafad89a5e103f31ea517c1edb56130578c3cd56`. Trace the selected benchmark
   #134 implementation from configuration to scheduler and connector classes.
   Prove it avoids the incompatible `RecomputeScheduler.schedule(self)` path,
   or prepare a minimal compatibility proposal/new paired SHA plus an
   interface-level CPU test. Do not silently patch an approved pin.

G0 exits only when the profile bytes, stage/call-site mapping, communication
dependency, and scheduler outcome are reviewable and the owner has explicitly
accepted the applicable digest and compatibility decision. A profile draft or
static audit alone is not a freeze.

Authenticated issue revalidation on 2026-08-03 found that profiler PR #3 is
merged at `7e10622eb5755e1af544546e93e3f63a91214ffc` and contributes Idle Evidence
Contract **Draft v4.3 (proposed for M0 approval)**. The latest issue-#2 comment
records its checked-in counterexample/CI contract and says the next acceptance
item is runtime matched A/B at one workload and collection boundary. v4.3
specifies proposed conservative idle-evidence vocabulary, interval algebra,
communication-interval canonicalization, clock alignment, and forbidden
claims; its checked-in fixture/CI boundary is real, but the document remains a
draft and does not define the closed runtime H2D/D2H operation roster,
`issue2:<version>:<subtype>` evidence codes, or KV-recovery call-site adapter
required by the frozen P0 protocol. Therefore it is a normative dependency and
useful design input, but it is not by itself authorization to enable a
non-`none` communication mode. Tiering remains blocked pending an explicit
issue-2-owner approval or an explicitly delegated specialty-profile authority;
the recovery-profile owner cannot unilaterally mint an active `issue2:*` code.

### G1 — controlled CPU whole-chain integration (no hardware)

Only after G0 approval, extend the existing bounded hook/exporter path with a
thin adapter and reviewed call sites. Do not create another exporter or add
file/log-handler I/O to producer paths. Preserve disabled-mode behavior,
fail-open serving, fail-closed evidence, explicit edges, exact IDs, process
receipts, terminal/cleanup ordering, and all frozen bounds.

The minimum exit evidence is one complete fake recovery episode and one valid
no-pressure trace, with tracing disabled and enabled. Tests must cover stage
loss/duplication/inversion, request/sequence/block drift, zero/overflow bytes,
zero/one/multiple reasoned requeues, prefill/decode resume, exact monotonic-ns
to offline-ms decomposition, version mismatch, exporter loss, incomplete
process rosters, and every selected scheduler/connector interface. Rerun any
CPU gate or independent review whose bound bytes change.

### G2 — read-only NPU6 admission

Run a version-aware whole-trace preflight only after G1 passes. Admission
requires exactly one marker: `READY.txt` with no `BLOCKED.txt`. Any missing,
ambiguous, incompatible, busy, stale-endpoint, wrong-model/device, schema,
profile, process-roster, or trace-export condition produces only
`BLOCKED.txt`; stop without launching or changing a service.

### G3 — one controlled online recovery smoke

After explicit service authorization and G2 READY, induce exactly one minimal
pressure episode and verify the complete request/sequence/logical-block/stage
chain plus copy/wait/requeue fields. Label the result `real-online` and
`smoke-only`. It proves capture coverage only, not speedup, representativeness,
or M0.

### G4 — fixed-8-GiB matched mechanism experiment

Only after a valid G3 trace, freeze mutually exclusive resolved configurations
for tiering-disabled, tiering-enabled, and HBM-only. Follow benchmark #134's
fixed model/hardware/context/workload settings and the combined performance
merge gate. Use the same requests and at least three independent service
lifecycles per mode in rotating/alternating order; report every repetition,
median/IQR, correctness, errors, raw artifacts, exact paired SHAs, environment,
profile, and resolved configuration. Observer tracing disabled/enabled and any
copy optimization on/off comparison are separate one-variable pairs.

### G5 — capacity/workload surface

After the fixed-8-GiB mechanism result is valid, expand to 8/16/24/32 GiB over
random-online, ShareGPT-online, and prefix-repetition-online at the frozen
arrival rate. An attempted row without a real recovery episode is negative
coverage, not tiering evidence.

### G6 — rank-one counterfactual and formal evaluation preparation

For every non-abstained top attribution, change only the predicted mechanism
and run a matched counterfactual. Formal P2/P3 scoring still requires Team-A
custody, fresh sealed positive/negative cases, frozen specialty targets,
comparator budgets, thresholds, and reveal rules; public #134 development
evidence does not satisfy blind scoring by itself.

### Immediate next deliverables

The active task is G0 only. Before any runtime source edit, create and review:

- `contracts/p1/kv-recovery-profile.v0-draft.md`: proposed profile and complete
  validation grammar;
- `docs/kv_recovery_runtime_callsite_map.md`: exact pinned-SHA symbols,
  state transitions, owners, identities, and evidence boundaries;
- `docs/pinned_pair_scheduler_compatibility.md`: configuration-to-connector-
  to-scheduler resolution, signature evidence, and GO/BLOCKED outcome; and
- a content-addressed approval candidate that clearly remains unapproved until
  the owner accepts its digest and decisions.

Static repository inspection and CPU-only contract tests are authorized for
this task. Runtime/device source edits, remote publication, NPU admission, and
service launch remain separate later actions.

### G0 static-audit checkpoint (2026-08-03)

The required read-only audit and candidate drafting are complete locally on
`feature/kv-recovery-profile-v1alpha1`; nothing from this branch has been
pushed. The proposed artifacts are:

- `contracts/p1/kv-recovery-profile.v0-draft.md`, SHA-256
  `b363532884d1cae8049ab080d2b85a629f3b33a75f6621788d1e4c8f30737666`;
- `docs/kv_recovery_runtime_callsite_map.md`, SHA-256
  `c518c031e0e4c73002e9c85777024771a10dce22d99587d71d08cf5b3b41d634`;
- `docs/pinned_pair_scheduler_compatibility.md`, SHA-256
  `3dea1d4dc9731122d9bd36b59da161a236e15680f4920051ce26ea07d8996a16`;
  and
- `contracts/p1/kv-recovery-profile-approval-candidate.json`, SHA-256
  `15a121505c413da6c8c90a0ce21c44ebe853b2db5fa3f81f6735e9185fedc612`,
  whose status is
  `profile_owner_review_required_and_issue2_mapping_pending` and whose gate
  effects are all false until an explicit profile-owner approval statement is
  recorded.

The profile proposes a separate `rlp.kv-recovery/v1alpha1` stream for one
host, TP=1, PP=1, rank 0, one pressure-preemption epoch, and one successful H2D
restore. It specifies candidate identities, the base-epoch-to-recovery-epoch
relation, seven stage boundaries, a worker child observation that does not
move the frozen base compute boundary, reasoned requeues, logical block sets,
run/process-scoped exact wait sets, transfer scope, monotonic-ns conversion, a
profile-specific loss ledger, process receipts, and fail-closed behavior
without changing `rlp.trace/v1alpha1`. It records `d2h_preserve`,
`h2d_restore`, and `transfer_wait` as proposed recovery-side operation labels
and contains only an H2D mapping fragment. They are not active issue-2 evidence
codes. A separate mapping artifact must bind the approved profile digest,
close all three span/edge grammars, and receive issue-2-owner (or explicitly
delegated specialty-authority) approval. Until then
`issue2:kv-recovery-v1alpha1` remains disabled. HBM-only/no-connector remains
the only candidate allowed to retain the existing `communication_mode=none`.

The static compatibility outcome is `BLOCKED`, with a narrower recommended
candidate rather than a blanket rejection of the source pins:

- runtime `f229ba7...` requires
  `schedule(self, throttle_prefills: bool = False)` and both EngineCore paths
  pass the boolean; device `cafad89...` implements
  `RecomputeScheduler.schedule(self)`, so installing it is incompatible and a
  one-argument cosmetic patch is insufficient;
- the device `NPUOffloadingSpec`/`NPUTieringOffloadingSpec` imports the removed
  `vllm.v1.kv_offload.worker.worker` module and uses old handler and
  `SharedOffloadRegion` APIs, so those classes cannot run on the pinned
  runtime;
- runtime `f229ba7...` already has its own `TieringOffloadingSpec` and Ascend
  `OffloadingWorker`. A full config that selects runtime-core
  `OffloadingConnector/TieringOffloadingSpec`, omits the device spec module,
  and explicitly keeps `recompute_scheduler_enable=false` statically avoids
  both known specialty blockers, but it is not a runtime GO until frozen and
  CPU/startup-tested; and
- benchmark `0858cdb...` contains no content-addressed issue-#134 14B,
  max-model-length-32768, 8-GiB three-mode configuration. Historical PR #124
  used 7B, 4608 context, 256 MiB device KV, 1 GiB CPU, and different SHAs; only
  its no-connector versus runtime-OffloadingConnector structure is reusable.

The audited runtime also distinguishes a real pressure preemption from
invalid-KV-load recovery. The latter does not necessarily enter
`PREEMPTED` or increment `num_preemptions`, so it must not be padded into a
seven-stage positive episode. Physical CPU/device block IDs, connector job
IDs, and scheduler step counters are local/reusable and cannot replace the
profile's explicit request/lifecycle/recovery/transfer/logical-block joins.

G0 has not exited. The next Remygred decision is to accept or replace approval
candidate items 1–8 and the profile digest; communication item 7 is only an
endorsement to prepare the separate content-addressed issue-2 mapping. Profile-
owner approval at most unlocks the remaining G0 work: draft that mapping,
freeze mutually exclusive issue-#134 resolved config bytes for HBM-only,
tiering-disabled, and tiering-enabled candidates, and then run import/
scheduler-interface/fake-handoff tests before any runtime source edit. The
mapping still needs its distinct issue-2-authority approval. Profile approval
does not itself unlock G1 wiring. Do not begin G1, NPU preflight, or a
performance run from the existence of these drafts.

## G0 owner approval and post-approval execution checkpoint (2026-08-03)

This section supersedes the “next Remygred decision” paragraph in the earlier
static-audit checkpoint. It records the exact approval and all work completed
from it; it does not rewrite the historical checkpoint.

### Exact owner approval and scope

Remygred supplied this exact statement:

> 批准按 SHA-256 b363532884d1cae8049ab080d2b85a629f3b33a75f6621788d1e4c8f30737666 冻结 rlp.kv-recovery/v1alpha1 恢复侧 profile 候选，并接受 SHA-256 15a121505c413da6c8c90a0ce21c44ebe853b2db5fa3f81f6735e9185fedc612 的 Approval candidate 第 1-8 项，其中第 7 项仅表示同意将 operation labels 和 H2D mapping fragment 提交 issue-2 authority 形成独立完整映射并联签；选择 runtime-core OffloadingConnector/TieringOffloadingSpec，recompute_scheduler_enable=false。该批准仅解锁剩余 G0 配置冻结和 CPU 兼容性测试，不授权 communication_mode 非 none、G1 runtime wiring、NPU 或性能实验。

The durable local record is
`contracts/p1/kv-recovery-profile-owner-approval.json`, SHA-256
`2831ce52802e7cbe4ec092431c71c18de05491da7ac8d48512014b1d43b3cb0c`.
It freezes these previously reviewed bytes without editing them:

- recovery profile
  `b363532884d1cae8049ab080d2b85a629f3b33a75f6621788d1e4c8f30737666`;
- profile approval candidate
  `15a121505c413da6c8c90a0ce21c44ebe853b2db5fa3f81f6735e9185fedc612`;
- runtime call-site map
  `c518c031e0e4c73002e9c85777024771a10dce22d99587d71d08cf5b3b41d634`;
  and
- pinned-pair scheduler decision
  `3dea1d4dc9731122d9bd36b59da161a236e15680f4920051ce26ea07d8996a16`.

The owner's later instruction to work more aggressively means use available
G0 autonomy, parallel read-only audit, explicit candidates, and proportionate
CPU validation to advance quickly. It does **not** broaden the enumerated
authorization boundary. In particular, it is not permission to enable
non-`none` communication, edit runtime/device sources, start G1, touch NPU,
launch a service, run performance experiments, publish remotely, or make
performance/M0 claims.

### Subsequent P0-overlay and G1 implementation authorization

After the G0 evidence package was committed and pushed, Remygred supplied this
exact statement in direct response to the immediately preceding permission
scope:

> 我现在将我能批准的权限全部批准，然后按照你说的做

The immediately preceding incorporated scope was exactly the Chinese G0 Draft
PR plus separate-branch default-off G1 authorization preserved in the records;
it did not itself cite the overlay digests or accept items 1–8. The same
assistant message separately identified the current overlay SHA-256
`6e035c29664038cdc93b545538cee6fc31abfb79e455d994851f8c9dbfd1c734`
and approval-candidate SHA-256
`169c1923ed2d37fe0ea5f88d05bcc9e35424742bb53892408ac5059485609cb5`;
the pending record keeps those only as resolved context, not owner
ratification. Preserve the exact reply and incorporated scope; do not interpret
“all permissions I can approve” as issue-2 authority, digest ratification, or
approval of unresolved configuration values.

The pending P0-owner ratification record is
`contracts/p1/kv-offload-base-mode-overlay-owner-approval.json`, SHA-256
`c17dad09ab005c839ad5cd52c0d65cb0c7ad9064ad9431deed10e8b7a99aa782`.
The general reply does not itself satisfy the overlay candidate's requirement
for an explicit reply citing both final digests and accepting items 1–8, so
this record freezes nothing and carries the exact ratification text still
required. It also cannot substitute for issue-2, complete-configuration, or
joint-admission authority.

The independent implementation authorization is
`contracts/p1/g1-cpu-wiring-owner-authorization.json`, SHA-256
`82386d4328463c8d7c32ad572f429a350af42bb04f8dda552e049788b88c6ecd`.
It authorizes an isolated branch/worktree at runtime pin
`f229ba7cad21a4dba58681af6738a9fd947388e2`, default-off runtime/profiler
source edits, bounded in-memory H2D context propagation, profile-only D2H/wait
adapters, and CPU-only tests. It does not authorize device-plugin edits,
runtime activation, non-`none` communication, NPU import/execution, service
launch, performance experiments/claims, M0, a remote G1 PR/push, or merge to a
default branch. Issue-2 mapping changes or approval decisions still require
revalidation.

`tests/test_owner_authorization_integrity.py`, SHA-256
`0332976e559c9caae9484121f29abd55d32c824fcba6b8ef766cb4a5d2328523`,
binds both authorization records to the exact artifacts and proves that only
default-off G1 source implementation is open. It passes 2 focused tests; the
repository suite after adding these records is 134 passed. This later result
does not rewrite the content-addressed 132-test G0 CPU result.

The G0 evidence package is published as Draft PR
`intellistream/vllm-request-lifecycle-profiler-plugin#7` from
`feature/kv-recovery-profile-v1alpha1`; its first authorization-record head is
`a80f2f69de0bd042eff4c3b53d8b606c78df7961`. Profiler issue #2 comment
`5163670652` requests Luqhhh/delegated authority review of mapping SHA-256
`dca914f989f3a98d43fb9fa2538f7c43a375e8f22f5deb7e09343aee5ee7bc19`
and approval-candidate SHA-256
`f3cfdd6d9463251fdc27e01164d9f33a1efcc6c155f6d51959e0e1989d23a350`.
The PR and request are publication/review facts only; neither is an approval or
activation record.

### Latest authenticated authority facts

Authenticated revalidation after the approval found:

- profiler issue #1 comment `5162001363`: PR #5 is merged; the order remains
  profile/communication freeze, resolve the pinned scheduler API mismatch,
  CPU whole-chain work, then read-only preflight. No tiering/HBM experiment
  precedes those gates;
- profiler issue #2 comment `5162001498`: observed stream universes and scan
  completeness are per-device before run aggregation; an unassigned-stream
  sentinel creates no timeline and forces incomplete scan status; legal
  zero-duration wait/control/record observations are points only; productive
  or unknown zero-duration intervals are invalid; checked-in fixtures do not
  replace runtime-matched A/B;
- remote profiler `main` is
  `a27794afa9f3fba11c6da17f06df7ed41e6fee3f`, the PR-#5 merge. The local
  branch remains intentionally based on PR-#5 head
  `06c8fa96ff056d3326d79b2756b106af7f916749`; do not silently rebase;
- benchmark #134 still has no comments and requires Qwen2.5-14B-Instruct,
  FP16, one 910B2, `max_model_len=32768`, device KV 8/16/24/32 GiB, three
  named online workloads at 1 RPS, at least three independent service
  processes, and the fixed-8-GiB three-mode state-machine comparison; and
- benchmark #89 keeps the mainline defaults
  `gpu_memory_utilization=0.6`, `max_model_len=32768`, 14B/one-910B2/FP16,
  while specialty comparisons must remain separate and explicitly resolved.

### Issue-2 mapping result and independent P0 blocker

The complete specialty candidate is
`contracts/p1/issue2-kv-recovery-mapping.v0-draft.md`, SHA-256
`dca914f989f3a98d43fb9fa2538f7c43a375e8f22f5deb7e09343aee5ee7bc19`.
An independent read-only review gave it GO for authority submission, not for
activation. Its approval candidate is
`contracts/p1/issue2-kv-recovery-mapping-approval-candidate.json`, SHA-256
`f3cfdd6d9463251fdc27e01164d9f33a1efcc6c155f6d51959e0e1989d23a350`.
Luqhhh or an explicitly delegated issue-2 specialty authority must accept or
replace all eight items while citing both digests.

The closed mapping roster is deliberately asymmetric:

- `h2d_restore`: exactly one base start/done span and three edges:
  closing `preempted(e)` to `communication_started(e+1)`, start to done, and
  done to the first `admission_started(e+1)` after successful scheduler
  wakeup;
- `d2h_preserve`: exact successful profile submit/done facts, zero base spans,
  and zero base edges; and
- `transfer_wait`: one process/run-scoped wait-entry point with exact member
  chunks, zero base spans/edges, no request fan-out, and no invented duration.

The wait mapping resolves/fixes membership and captures `wait_entry_ns` before
the existing call, enqueues chunks only after normal return, gives every chunk
that entry timestamp, and derives `wait_call_observation_id` from the first
chunk's unique `record_id`. Repeated identical member sets remain distinct
without adding a wire field. Missing/interleaved/drifting chunks fail closed.

The H2D internal edge additionally requires explicit propagation through a
bounded process-local pending table keyed by `transfer_id`; timestamp/process
order alone is insufficient. The hard limit is
`max_pending_h2d_contexts_per_process=4096`. A full table does not reject,
delay, cancel, or resize the real KV transfer. It consumes one attempted
profile `transfer_event` `record_seq`, opens/extends the exact
`serialization_failure` loss interval, emits no corresponding base pair/edge,
and fails only formal evidence closed.

Issue-2 approval is necessary but not sufficient. Frozen P0 allows only
`kv_cache_mode=disabled|local_homogeneous`, requires no KVConnector for the
latter, lists connector-backed caches as diagnostic-only, and gives generic
paired-operation/execution-child wording. Therefore the connector path also
needs a P0-owner mode overlay that explicitly accepts:

1. one truthful connector-capable mode;
2. the H2D-only base-operation roster while D2H/wait remain profile-only; and
3. the cross-epoch `preempted -> H2D -> next admission` recovery bridge.

The minimal proposal is
`contracts/p1/kv-offload-base-mode-overlay.v0-draft.md`, SHA-256
`6e035c29664038cdc93b545538cee6fc31abfb79e455d994851f8c9dbfd1c734`.
It proposes `kv_cache_mode=local_offload` under
`rlp.trace-mode/kv-offload-v1alpha1`, binds the P0/profile/mapping/final-config
digests, covers only the proposed `tiering_enabled` TieringOffloadingSpec row,
and otherwise preserves P0. Its independent content review is GO for authority
submission, not approval. The P0-owner approval candidate is
`contracts/p1/kv-offload-base-mode-overlay-approval-candidate.json`, SHA-256
`169c1923ed2d37fe0ea5f88d05bcc9e35424742bb53892408ac5059485609cb5`.
It remains `p0_owner_review_required`; do not use its digest as a runtime
binding until explicit P0-owner approval is recorded.

Activation later requires a separate joint admission record binding the
overlay and overlay-approval-record SHA, mapping and issue-2-approval-record
SHA, complete config and config-approval-record SHA, profile/owner-record SHA,
and P0 contract/taxonomy approvals. Remygred/P0 owner and the #134
configuration authority must co-sign that record; their signatures cannot
substitute for the separate issue-2 authority.

### Fixed-8-GiB configuration candidate

The reviewable but deliberately incomplete candidate is
`contracts/p1/benchmark-134-fixed-8gib-config-candidate.json`, SHA-256
`b57fed50aa067e937728fe6f618a37246c50becd5ac94bd8eef3bc2ee7184b3a`.
Its status is `BLOCKED_INCOMPLETE_NOT_RUNNABLE_NOT_FROZEN`; its nulls are
intentional and must never be replaced silently. Its formal-dependency block
binds the final mapping/approval-candidate and overlay/approval-candidate
digests while accurately recording that issue-2/P0 approval records, the
complete config, and the joint admission record do not yet exist. The overlay
references only this candidate's path as non-normative input, so there is no
digest cycle. This candidate remains a content-addressed pre-ratification
snapshot: the later G1 authorization does not make it runnable, and any future
explicit overlay ratification must be cited by a new replacement configuration
artifact rather than editing these bytes in place.

Known common choices include:

- device KV is exactly 8 IEC GiB per device = `8589934592` bytes;
- TP=PP=DP=1, Qwen2.5-14B-Instruct, FP16,
  `max_model_len=32768`, and recorded `gpu_memory_utilization=0.6`;
- `recompute_scheduler_enable=false`,
  `SLO_limits_for_dynamic_batch=-1` as a pinned-source compatibility candidate,
  and default/null runtime scheduler class;
- HBM-only has no connector and retains `communication_mode=none`;
- tiering-enabled resolves through runtime-core
  `OffloadingConnector/TieringOffloadingSpec/AscendCPUOffloadingWorker`, omits
  both connector/spec module override paths, and never uses device NPU specs;
- `max_num_batched_tokens=4096` and `max_num_seqs=512` are explicit nondefault
  design candidates, not claimed Ascend defaults (the pinned fallback remains
  2048/256);
- 200 requests, 1 RPS, seed 0, with proposed random 1024/256 and prefix
  10×3840-prefix/256-suffix/256-output shapes derived from pinned canonical
  references; exact request manifests remain required, and repetitions are at
  least three independent services for every workload/mode pair;
- required metric coverage is unresolved; `disable_log_stats=false` is only a
  candidate, and profiler-disabled/enabled overhead is a separate future axis
  that is not authorized; and
- the current runtime has no unique copy-optimization Boolean. Staging-buffer
  size and layout permutation are not substitutes, so the optional pair is
  `BLOCKED_NO_UNIQUE_ON_OFF_SWITCH`.

The unresolved authority inputs are:

1. one exact positive `cpu_bytes_to_use`, identical across connector modes;
2. explicit acceptance or replacement of
   `tiering_disabled = OffloadingConnector + CPUOffloadingSpec` so it does not
   duplicate HBM-only; this family is outside the current profile-owner choice
   and needs a new profile digest or separately reviewed compatible-pair owner
   record plus a new/expanded overlay;
3. exact model revision/local snapshot approval. The local complete candidate
   is `cf98f3b3bbb457ad9e2bb7baf9a0125b6b88caa8`, but observation is not a
   freeze;
4. content-addressed random, ShareGPT, and prefix request manifests, including
   arrival schedule and sampling/`ignore_eos` choices;
5. an exact metric source for every #134 metric and the separate profiler
   overhead axis;
6. a real copy switch or explicit acceptance that the optional comparison is
   unavailable; and
7. the issue-2 mapping plus P0 overlay approvals for connector modes.

No complete server/client argv exists while those values are unresolved.
Do not launch from this candidate.

### CPU pinned-pair evidence

`scripts/verify_g0_pinned_pair.py`, SHA-256
`3e5c666f63969f523f8f70c07ed8c5141706887b11a775c757b4dc12cf69df3f`,
reads exact Git objects rather than either dirty sibling worktree. Its tests are
`tests/test_g0_pinned_pair_probe.py`, SHA-256
`4ad8e5162f0c91f3fcd188a78ba602dd576d97c322cd8f596d545c674f6ace4f`.
Configuration and cross-artifact tests are respectively
`tests/test_g0_benchmark_134_config_candidate.py`, SHA-256
`5b4823a90e022b4463d2f2899f9aae522bbb62185826d7ee1b8fa55604372e85`,
and `tests/test_g0_contract_candidate_integrity.py`, SHA-256
`e1e41b48f36e6afc17444d5f659a3824d953430706c94c3878002d97289e729c`.

The local G0 run verified 19 exact blob SHA-256 values (13 runtime and 6
device-plugin blobs) and passed:

- runtime `SchedulerInterface.schedule` and `Scheduler.schedule` are
  `(self, throttle_prefills=False)` and EngineCore passes the Boolean at both
  pinned call sites;
- device `RecomputeScheduler.schedule(self)` and
  `SchedulerDynamicBatch.schedule(self)` remain incompatible negative
  controls. Both must be disabled, not merely the recompute path;
- runtime registries resolve `OffloadingConnector` and
  `TieringOffloadingSpec`, the device plugin neither removes nor overrides the
  connector, and the Ascend branch selects runtime
  `AscendCPUOffloadingWorker`;
- the device NPU spec still imports removed
  `vllm.v1.kv_offload.worker.worker`, whose path is absent at the runtime pin;
  and
- a controlled-stub execution of the pinned worker preserves only connector
  job ID, runtime request ID, source/destination specs, and wait-set job IDs;
  a separate observer ledger validates synthetic trace/lifecycle/epoch/
  transfer/block identities, 8192 bytes, 12,500,000 ns, and negative cases.
  This does not prove the pinned worker propagates recovery-profile identity.

The probe binds both the exact candidate byte digest above and canonical
semantic digest
`d6520a785d566b6509532c59de01c33abdee7ebbfee41f1cba76c42b695dc54d`.
Any byte drift fails at the file entry and any semantic drift fails at the
in-memory entry, including added authorization keys or changed connector/spec
fields.

The final results are 27 probe tests, 5 config tests, and 6 cross-artifact
integrity tests (38 focused total); the complete repository suite is 132
passed. Targeted Ruff check and format check pass. The durable result is
`contracts/p1/g0-pinned-pair-cpu-result.json`, SHA-256
`8fb3a1aa5f912c2b43a68cef6952d4d6ff365d1154008287a21306bc7241ee5c`.
The direct probe intentionally exits 2 with:

```text
static_source_contract_status=PASS_STATIC_ONLY
overall_status=BLOCKED
reason_code=REAL_PINNED_IMPORT_ENVIRONMENT_UNPROVEN
```

The prescribed profiler Conda environment has no `vllm`, `vllm_ascend`,
`torch`, or `torch_npu`. The available `/root/vllm-hust/.venv` points to dirty,
newer runtime/device heads and conflicting plugin metadata, so it must not be
used as pinned-pair evidence. AST and controlled-stub results do not prove a
genuine full pinned import, platform startup, sidecar integration, producer
no-I/O behavior, or runtime wiring. Those remain blocked; never relabel
`PASS_STATIC_ONLY` as GO.

The local-pin pytest cases require sibling repositories containing both pinned
commits and explicitly skip when those repositories/objects are absent;
portable config/integrity cases still run. A future CI result must report such
skips and must never claim the pinned-source audit passed unless the exact
objects were provisioned.

### G1 default-off runtime transfer-spine checkpoint (2026-08-03)

The authorized isolated runtime checkpoint is now implemented, independently
reviewed, and committed **locally only**:

- repository/worktree: `/root/vllm-hust-g1-default-off-f229ba7`;
- branch: `feature/rlp-kv-recovery-g1-default-off`;
- exact base: `f229ba7cad21a4dba58681af6738a9fd947388e2`;
- local head: `0141462f82fb32f78129acccc996212296129eac`;
- commit subject: `kv offload: add default-off recovery identity spine`; and
- remote status: **not pushed; no G1 PR exists and no merge is authorized**.

This is a reviewed **G1 transfer-spine WIP**, not a completed or activated G1
implementation. It adds the runtime-side identity/transport seam needed for a
future profiler adapter while keeping the production activation gate closed.
It does not implement the real profiler evidence sink/exporter, the complete
seven-stage recovery instrumentation, configuration/joint admission, or a
formal run manifest.

The committed source/test SHA-256 values are:

- `vllm/v1/kv_recovery_profile.py`:
  `f971272aa076c669c27a2f64a81f024f7593a77c5210c546f862e7e30ee62074`;
- `vllm/distributed/kv_transfer/kv_connector/v1/offloading/common.py`:
  `88051c44fc9ae7b73381971f02f532d65e52bbad9e2f97674abfbddb285bd77c`;
- `vllm/distributed/kv_transfer/kv_connector/v1/offloading/scheduler.py`:
  `88039706eb91ac63cd31dbc9967b4c616522adbaf58fc7bc7e6bd826f237a0c9`;
- `vllm/distributed/kv_transfer/kv_connector/v1/offloading/worker.py`:
  `2da4857a7f7607d10aa15124e734384b3b2b06dff2e3abdfe048fd4135f5aa6c`;
- `vllm/distributed/kv_transfer/kv_connector/v1/offloading_connector.py`:
  `7cfd4a1eb716c2b2669c375bb2dfc50479e330526112e8d76c2daf7aba9916d6`;
- `tests/v1/test_kv_recovery_profile.py`:
  `971deca636cdec181cf6574f2ccd7b715a64658c7bad09d53ac9b7ce29991033`;
- `tests/v1/kv_connector/unit/offloading_connector/test_kv_recovery_scheduler.py`:
  `8c8925c523c378a368eaedfd526219d5c30c80bc40ba5d8e1f20c8999717b3e0`;
- `tests/v1/kv_connector/unit/offloading_connector/test_kv_recovery_worker.py`:
  `0507227ebad9c567f230866b59a75b2a0ac2937235c3e778c200154090e67c74`;
  and
- `tests/v1/kv_connector/unit/offloading_connector/test_worker_metadata.py`:
  `0cdbf72e54a169dbcfb21a2b3bd48b87d07bceda504e7d7c8a74aef7e64eb5e2`.

Any byte change invalidates the review result below. Rerun the full focused
suite, targeted regressions, Ruff/format/diff checks, and independent scope
review before replacing this checkpoint.

#### Implemented transfer-spine behavior

- `KV_RECOVERY_RUNTIME_ACTIVATION_AUTHORIZED` is false. The effective gate
  additionally requires the binding's activation bit, approved issue-2
  mapping status, approved P0-overlay status, and
  `communication_mode == communication_mapping_id`. The committed binding is
  `false / pending / pending / none`; changing only one Boolean cannot
  activate it.
- Even after a future joint gate opens, observer creation is limited to exact
  `type(spec) is TieringOffloadingSpec` with an explicitly resolved
  `recompute_scheduler_enable is False`. `CPUOffloadingSpec`, subclasses,
  custom specs, device NPU specs, a missing value, and `True` fail closed.
- No production code registers a factory. With the gate closed, registration,
  creation, fork preparation, and reinitialization return before touching the
  factory lock or plugin. `worker_base.py` has no diff. The normal scheduler
  and worker hold no recovery context/attempt tables and do not read the
  profile clock or call an evidence sink.
- Scheduler D2H/H2D logical coordinates are canonicalized and capped at 4096
  plus one bounded overflow sentinel. Contexts travel in optional connector
  metadata rather than changing `TransferJob`. Over-bound or malformed
  observer results fail evidence closed while the real transfer path proceeds.
- The worker allocates a process-scoped transfer ID before backend submission,
  captures the submit point immediately after accepted backend return, and
  captures completion at the first successful raw `TransferResult`
  observation. A clock or submit-observer failure cannot retain an attempt or
  later emit a receipt.
- The reference worker observer binds exact process UUID, run ID, clock domain,
  rank/world, job/transfer/context/block identities, strict uint domains, and
  exact bytes/timestamps. Python `bool` and `float` cannot pass integer fields.
  Forked children replace inherited locks, reinitialize an inherited factory
  once, clear it on failure, and may register a fresh child factory without
  weakening same-process single registration.
- H2D pending contexts and transported receipts have hard 4096 limits. The
  4097th real H2D transfer still submits and completes for serving, consumes
  one bounded `serialization_failure` evidence attempt, emits no base receipt,
  and disables affected formal evidence without an unbounded tombstone table.
- D2H remains profile-only and cannot emit an H2D/base receipt. Equal H2D host
  timestamps may reach the profile sink as diagnostic point evidence but
  cannot emit a zero-length base span; equal D2H submit/done timestamps fail
  before formal profile completion.
- Worker wait membership is resolved before the existing backend wait and
  copied only up to a 4097-member overflow sentinel. The original backend set
  is never truncated. A valid wait captures one entry timestamp immediately
  before the call and is recorded only after normal return; there is no return
  timestamp or invented duration. Missing, failed, foreign-run/process, mixed,
  malformed, or over-bound membership fails evidence closed.
- Observer/factory/sink exceptions and malformed returns never reject, delay,
  cancel, resize, or alter the real submit/wait/completion result. Scheduler
  reset and shutdown and worker shutdown close observers best-effort; serving
  exceptions from the real backend retain their original behavior.

#### Validation and review evidence

The final focused CPU command covered the new ABI, scheduler/worker sidecar,
metadata, hard-off, fork, close-race, strict identity, capacity, overflow,
clock ordering, wait, reset, malformed-observer, and fail-open cases:

```text
66 passed, 15 warnings
```

Seven unchanged reset/event/metadata regression cases also passed. Targeted
Ruff check, Ruff format check, Python compilation, and `git diff --check`
passed. Three independent read-only reviews returned GO only for the local
default-hard-off CPU transfer-spine WIP and found no remaining blocker in the
closed path, fail-open serving behavior, bounds, identity, time points, fork,
or authorization scope.

Two pre-existing Tiering end-to-end tests remain unavailable because
`meta-llama/Llama-3.2-1B-Instruct` returns Hugging Face 401 gated-repository
errors. The exact two failures reproduce at unmodified base
`f229ba7cad21a4dba58681af6738a9fd947388e2`; do not attribute them to this
commit and do not claim those end-to-end tests passed. An earlier broader
offloading-directory checkpoint reported 125 passed, 13 failed, and 2 skipped;
the 13 failures were the pinned CPU/environment baseline lookup and
multi-group/Eagle fixture failures, not a green full-suite gate.

#### Remaining gates and next work

This checkpoint remains NO-GO for all of the following:

1. issue-2 mapping approval by Luqhhh or explicitly delegated authority;
2. explicit P0-owner overlay ratification citing both required final digests
   and accepting items 1–8;
3. a complete resolved #134 configuration, configuration-authority approval,
   and the multi-authority joint-admission record;
4. real profiler observer/sink serialization, loss/export receipts, complete
   seven-stage recovery joins, and whole-trace/DAG CPU validation;
5. an isolated genuine pinned startup/import result;
6. a separate reviewed runtime-activation authorization; and
7. any remote G1 push/PR, merge, non-`none` communication, device-plugin edit,
   NPU command, service launch, performance experiment/claim, or M0 claim.

Do not activate by editing the gate or binding in place. After authorities and
complete config exist, create new content-addressed admission records, update
the binding in a separately reviewed change, rerun all CPU/startup checks, and
request activation explicitly. Until then, further authorized work must stay
on isolated local branches, default off, CPU-only, bounded, and independently
reviewed.

### Current gate table and next order

The current formal status is:

- recovery-side profile: **FROZEN** by Remygred;
- issue-2 mapping content: **GO FOR AUTHORITY SUBMISSION**, not approved;
- P0 connector-mode overlay content: **GO FOR AUTHORITY SUBMISSION**, not
  yet explicitly digest-ratified by the owner;
- #134 fixed-8-GiB config: **REVIEWABLE INCOMPLETE CANDIDATE**;
- pinned source/scheduler/factory/controlled-stub handoff:
  **PASS_STATIC_ONLY**;
- G1 CPU-side default-off transfer-spine source implementation on an isolated
  branch: **LOCALLY COMMITTED AND REVIEWED WIP** at runtime
  `0141462f82fb32f78129acccc996212296129eac`, not pushed;
- genuine pinned import/startup and G1 runtime activation: **BLOCKED**;
- `communication_mode` non-`none`, device-plugin edits, NPU, service,
  performance, M0:
  **NOT AUTHORIZED**.

Continue in this order:

1. keep G0 Draft PR #7 unchanged while following up the already-published
   issue-2 request for Luqhhh/delegated approval of the mapping digest and
   eight decisions;
2. obtain the exact Remygred/P0-owner digest-and-items ratification preserved
   in the pending overlay record;
3. preserve the reviewed runtime transfer-spine commit above; any continuation
   toward the real profiler observer/sink and seven-stage joins must remain
   default-off, isolated, CPU-only, bounded, locally committed, and separately
   reviewed without claiming complete G1;
4. resolve the #134 CPU capacity, tiering-disabled semantics, model revision,
   workload manifests, metric coverage, and copy-toggle decision; then produce
   complete self-contained per-mode configs, obtain configuration-authority
   approval, and create the required joint admission record with new digests;
5. provision an isolated exact-pinned CPU import environment and rerun import,
   interface, config-resolution, and controlled-stub handoff checks without
   importing the device NPU spec or allocating hardware; and
6. only after every G0 authority, complete config, joint record, and G1 CPU
   review is complete, request separate runtime-activation authorization.

Except for the explicitly authorized G0 Draft PR publication, issue-2 approval
request, and independent-branch local G1 source commits, no remote G1 push/PR,
merge, rebase, service, NPU command, or performance run is authorized by this
checkpoint.

## Local P1 checkpoint (2026-08-02)

The parent-side candidate is committed on `feature/m0-protocol-freeze` at
`9f1464b8d017ef48e66b8b4c9bd4a5a37fdc563d`. Its audited implementation
surface is:

- `src/vllm_request_lifecycle_profiler/runtime_protocol.py`: strict frozen
  `rlp.trace/v1alpha1` builders, deterministic JSONL, bounded metadata and IDs,
  provenance, loss controls, and process start/summary records;
- `src/vllm_request_lifecycle_profiler/runtime_hooks.py`: the sole bounded
  exporter and fail-open facade;
- `src/vllm_request_lifecycle_profiler/legacy_trace.py`: explicit read-only
  compatibility reader for historical nine-event JSONL; and
- `tests/test_runtime_protocol.py` and `tests/test_runtime_hooks.py`: focused
  protocol, capacity, failure, timeout, concurrency, FD, and fork coverage.

The audited candidate SHA-256 values are:

- `__init__.py`:
  `5049669a52b899a478cfb3c9d997cf4d1933faa577dbed42d6cd263b38ab57da`;
- `legacy_trace.py`:
  `c3ecb2152cd495b6d86de9be4e771dbaa8c36a2855036c6fc72a2319093c1216`;

- `runtime_hooks.py`:
  `8ea700c38359822a5463da703ce280d87b11fbd90a733b0141bc6cb2206b5281`;
- `runtime_protocol.py`:
  `42a4127c36d346ae6bf0f6cee76d47496c6221ee815ef2cb7ebbb7ae3943b5d9`;
- `test_runtime_hooks.py`:
  `f5cfed74e4eb584ef816daa760ba05a0b4f6b955c21da5850d8e93ba02017882`;
- `test_runtime_protocol.py`:
  `7e35e1ebee37bca39aef9f2dff9a70696f1555d5df822ce130508503564c9b17`.

Two independent read-only review paths gave the four core files above a GO.
One additionally ran 50 rounds of 64 concurrent `close()` calls and real
2000-ms lock-contention probes. A GO is invalid if any bound byte changes;
rerun focused tests and both reviews after such a change. Treat the two small
export/compatibility files as part of the same immutable handoff even though
the concurrency reviews bind only the four core files.

That GO is limited to CPython 3.11, cooperative exporter processes, and a
trusted exporter-owned output directory. A deliberate same-UID pathname
replacement between inode validation and final `os.replace` is outside the
frozen threat model and remains a recorded TOCTOU hardening risk. If the threat
model expands to concurrent external directory mutation, invalidate this GO
and implement an independent UUID token, source-inode-bound publication, and
atomic no-replace semantics before accepting evidence.

Key implementation facts that the runtime port must preserve:

- Producers perform bounded validation, serialization, loss accounting, and
  enqueue only. They never open/write/close a file or invoke arbitrary logging
  handlers. The writer thread logs each frozen diagnostic reason at most once.
- One writer thread owns each `O_EXCL`, mode-`0600`, per-process append shard,
  including process start, data, loss records, summary, and descriptor close.
- Queue limits are 4096 ordinary plus 64 reserved records, 17,039,360 total
  queued bytes, 128 records/262,144 bytes per batch, and 100 ms writer interval.
- `close()` uses one deadline from public entry, including acquisition of the
  close lock and condition, and an immutable single-winner result claim. The
  CPython implementation uses one GIL-atomic `dict.setdefault`; an alternate
  Python interpreter requires a replacement primitive and a new audit.
- Before writing any summary, the actual shard is hard-linked to an
  `.incomplete.<monotonic_ns>` name and its formal name is atomically replaced
  by an empty mode-`0600` sentinel. This preserves UUID ownership. Only a fully
  drained shard, after descriptor close and diagnostic work, replaces that
  sentinel. A timeout winner forces asynchronous retraction or invalidation.
- The raw formal path is not an admission receipt. Run-manifest construction
  must use `committed_shard_path`, which is non-null only for the immutable
  `CloseResult(close_outcome="drained", summary_written=True)` winner. Never
  use a glob or a valid-looking file alone: if late retraction, unlink, and
  invalidation all fail, bytes can remain while the receipt still fails closed.
- Build the expected-process roster independently before collecting receipts.
  Every expected process must return a successful committed path; one missing,
  timeout, or failed receipt rejects the entire run manifest. Never use
  `filter(None)` or otherwise omit a failed process and call the run complete.
- Every `process_summary`, including timeout invalidation summaries, consumes
  the 64-record/byte reserved budget and releases it on success or failure.
- Exporter diagnostics are the frozen ten-value closed enum. A non-`none`
  communication configuration maps to exporter diagnostic `unsupported_mode`;
  `communication_subtype_unfrozen` remains only an unsupported-root reason.
- Forked workers must call `RuntimeLifecycleHooks.reinitialize_after_fork()` at
  an explicit worker-bootstrap boundary. Never lazily open a child shard from
  the first event-emission hot path.

The local CPU validation checkpoint is:

- focused protocol/exporter suite: 58 passed;
- complete repository unit suite: 89 passed;
- shared workload smoke: 26 supported cases passed and 2 documented external
  boundary cases skipped; the checked-in JSON/Markdown SHA-256 values remain
  `02f06b130856fa64fcfa1406ed5185e8ea23edd94d7ff4b0627a28015c73c765`
  and `ad1c1c3aa36f30e943721fdf72fb66a9aa8d0bb3943bfda689b99d5e0f9a1a0e`;
- targeted Ruff check and format-check for the five new/changed runtime and
  focused-test files: passed;
- package import smoke and `pip check`: passed; and
- isolated sdist/wheel build: passed and includes protocol, exporter, and legacy
  modules.

The broader project-owned Ruff scope (`src tests .benchmarks scripts`) is not a
clean gate: it reports 20 pre-existing issues in unrelated historical files;
`ruff check .` also enters vendored/submodule trees and reports 175 total. Do
not claim full lint success and do not rewrite those unrelated files as part of
the runtime port. No NPU process or managed inference service was started for
this checkpoint.

## Runtime invariants

- Tracing is disabled by default and must not change scheduling or outputs.
- The serving hot path performs only bounded in-memory work. File open, flush,
  write, drain, and close belong to the exporter path.
- All profiler initialization, serialization, enqueue, writer, and shutdown
  failures are fail-open for serving and fail-closed for formal evidence.
- Extend the existing hook and `JsonlTraceSink` path; do not introduce a
  competing exporter or silently redefine a legacy event.
- Never infer causal edges from process-global sequence or timestamp order.
  Causal edges require an explicit supported evidence source and an acyclic
  graph.
- Payload text, tokens, messages, auth data, client IPs, and raw model output
  are forbidden in traces by default.
- Queue/admission observations must not depend on optional stats logging.
- Preserve the current EngineCore order: emit its terminal, trace the real
  `_free_request` cleanup, then let root-scope frontend output processing
  observe the returned EngineCoreOutput. Never delay KV release for tracing.
- P1 completeness is decoder-only, local homogeneous KV-cache, `n=1`, and no
  frontend stop-string path; excluded modes emit a bounded diagnostic.
- Formal P1 traces remain restricted to `communication_mode=none` for the
  HBM-only/no-connector control. The approved recovery-side profile is not
  sufficient to enable a non-`none` mode: connector traces additionally need
  the separately frozen issue-2 mapping, the P0 base-mode overlay, a complete
  resolved configuration, and later authorized implementation gates.
- Respect the exact record sizes, queue bounds, terminal precedence, cleanup
  roster, supported-mode grammar, loss accounting, and compatibility behavior
  in the digest-bound
  `contracts/p0/runtime/minimum-runtime-contract.v0-draft.md`.

## Development and validation workflow

Use the project conda environment `vllm-request-lifecycle-profiler-exp`. In the
current machine layout it exists, uses Python 3.11.15, and its interpreter is:

```text
/home/shuhao/miniconda3/envs/vllm-request-lifecycle-profiler-exp/bin/python
```

The interactive shell carries unrelated Ascend `PYTHONPATH` and
`LD_LIBRARY_PATH` entries. Every CPU validation must isolate them explicitly:

```bash
env -u PYTHONPATH -u LD_LIBRARY_PATH \
  PYTHONNOUSERSITE=1 \
  PYTHONPATH=/root/vllm-request-lifecycle-profiler-plugin-kv-integration/src \
  PYTHONDONTWRITEBYTECODE=1 \
  /home/shuhao/miniconda3/envs/vllm-request-lifecycle-profiler-exp/bin/python -B \
  -m pytest -q
```

If the prescribed environment later disappears, report tests as blocked and
restore it before P1 tests. Do not substitute system Python, bare pip, or an
ad-hoc `.venv` and then report success. The environment currently has
setuptools 83.0.0 while `pyproject.toml` requires a build backend below 81;
therefore package verification must use the normal isolated `python -m build`
flow, never `--no-isolation`. Before NPU6 work, read `docs/next_agent_task.md`,
`docs/experiment_plan.md`, and the relevant runbook.

The parent CPU gate covered deterministic encoding, per-record validation,
bounded overflow/loss accounting, fail-open behavior, timeout/FD/fork safety,
and legacy compatibility. The next step is current-runtime call-site and
whole-trace grammar integration, including terminal/preemption/cleanup,
sidecars, the edge roster, DAG acyclicity, and streaming/non-streaming paths.
After those CPU integration tests pass, run the smallest supported NPU smoke
in each frozen execution mode. No formal blind run begins until the P2/P3
custody, targets, thresholds, comparator budget, and reveal protocol are
frozen.

## Evidence labels and claim boundary

Every artifact has exactly one source label:

- `real-online`
- `existing-server-probe`
- `replay`
- `simulation/model`
- `projected-profile`
- `derived-artifact`

This local source-label enum is distinct from benchmark
`metadata.data_source`, whose admitted real-online values may have a suffix or
come from an explicit CI allowlist.

Validity is a separate field. Never combine source labels, relabel replay as a
live run, or describe profiler-only analysis as a runtime speedup. Checked-in
historical cases and public candidates `vllm-hust#163`, `vllm-hust#151`, and
`vllm-ascend-hust#145` are development-only because Team B knows their
identities. Primary blind metrics require at least two fresh opaque positive
cases and one valid insufficient-evidence/no-single-root-cause negative case
under Team A custody.

For each non-abstained top prediction, require a rank-one counterfactual.
Report critical-path share, attribution precision, top-1/top-3 accuracy, MRR,
time-to-localize, trace overhead, cross-run variance, confidence, unexplained
residual, abstention, wrong-attribution severity, throughput, TTFT, TPOT/TBT,
P95/P99, error rate, peak device memory, and mechanism metrics as applicable.

## Performance implementation merge gate

Local work and a draft review may precede complete benchmark evidence. Merge
may not. The project gate combines benchmark #95's canonical artifact
admission rules with the matched-run and correctness rigor inherited from
vllm-hust #185; do not attribute every combined requirement to #95 alone. For
every performance implementation PR, official or specialty, require:

- exact target class, target ID/version/profile, and registry/spec hash;
- workload and fully resolved server/client configuration;
- matched base/head and exact paired core/device-plugin SHAs;
- at least three independent service lifecycles per side in alternating order;
- raw request/runtime artifacts and an environment manifest;
- `metadata.data_source` beginning with `real-online`, or an explicitly
  benchmark-allowlisted CI real-online source, plus canonical
  `leaderboard_manifest.json` and `run_leaderboard.json` inside the artifact;
- every repetition plus median and IQR;
- a correctness gate, reported error rate, and target-specific acceptance
  threshold;
- canonical artifact paths or URLs; and
- an explicit deviation and specialty reason when an official target cannot
  answer the question.

Missing, busy, skipped, cancelled, smoke-only, replay-only, or derived-only
evidence fails closed. The current active official registry targets enable
eager execution; graph-mode localization and matched observer-overhead studies
therefore need explicitly frozen specialty targets unless the registry changes.

## M0 evaluation acceptance and visibility

Before formal scoring, compare flat-summary and structured-DAG methods with the
same normalized-trace information and the same time budget. Team B receives
normalized traces only, never raw Team-A fault manifests, labels, salts,
openings, or oracle artifacts before diagnosis lock. The first executable
evaluation delivery includes at least one deterministic fixture, its exact
command, and raw output artifact so another agent can reproduce the scorer.

The inherited retrospective milestone is not satisfied by naming three public
issues: on at least two of the three development candidates, the method must
narrow the candidate set to at most two subsystems without relying on manual
log parsing. Those exposed cases remain development-only and do not count as
fresh blind accuracy evidence.

## Required reading before edits

- `contracts/p0/README.md`
- `contracts/p0/p0-manifest.json`
- `contracts/p0/owner-freeze-approval.json`
- `contracts/p0/runtime/phase-taxonomy.v0-draft.md`
- `contracts/p0/runtime/minimum-runtime-contract.v0-draft.md`
- `docs/next_agent_task.md`
- `docs/research_logic.md`
- `docs/claim_ledger.md`
- `CONTRIBUTING.md`

Within `third_party/vllm-hust`, its own `AGENTS.md` and nested instructions take
precedence for files in that submodule. Resolve any environment conflict with
the owner before modifying runtime code; do not blend two environment policies
silently.
