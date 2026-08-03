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
  `9f1464b8d017ef48e66b8b4c9bd4a5a37fdc563d`. Authenticated upstream `main`
  and the fetched local `origin/main` both point through merged PR #4 at
  `15717eae2630e80c11b113ccaeb3422871b35b40` as verified on 2026-08-03.
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
- P1 is restricted to `communication_mode=none`. A non-`none` `issue2:*` mode
  is out of scope until issue #2 supplies a separately frozen profile.
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
  PYTHONPATH=/root/vllm-request-lifecycle-profiler-plugin/src \
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
