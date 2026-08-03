# KV-Recovery Communication Mapping v0 Draft

- Proposed mapping ID: `issue2:kv-recovery-v1alpha1`
- Review status: `issue2_authority_rereview_required_after_request_changes`
- Activation status: `BLOCKED_BY_ITEM_4B_BASE_MODE_CONFIG_AND_AUTHORITIES`
- Evidence status: `NOT_M0_PROVEN`
- Runtime implementation status: `OUT_OF_SCOPE_FOR_THIS_MAPPING_CANDIDATE`

This is a content-addressing candidate for issue-2 authority review. It does
not edit the frozen P0 contract, activate a non-`none` communication mode,
authorize G1 wiring, admit hardware, or establish a performance result.

## 1. Purpose and authority boundary

This mapping binds the owner-approved recovery-side profile to the frozen base
trace and closes the treatment of three runtime observations:

- successful host-to-device KV restore (`h2d_restore`);
- proactive device-to-host preservation (`d2h_preserve`); and
- a worker call that blocks on a process-local transfer set (`transfer_wait`).

The roster is deliberately asymmetric. Only H2D has a request-scoped causal
bridge that the current P0 event/edge schema can express without invention.
D2H and wait facts remain in the recovery profile and have zero base-event and
base-edge cardinality in this version. A closed negative mapping is preferable
to fabricating a request return edge or duplicating one process-wide wait into
multiple request traces.

Remygred's profile-owner approval endorsed preparation of this mapping but did
not approve the issue-2 namespace. The issue-2 contract owner, Luqhhh, or an
explicitly delegated specialty authority must approve this artifact's final
digest. That approval still cannot override the separate base-mode blocker in
section 3.

## 2. Exact dependencies and execution baselines

### 2.1 Immutable semantic dependencies

| Dependency | Content identity | Status |
| --- | --- | --- |
| Minimum runtime contract | `contracts/p0/runtime/minimum-runtime-contract.v0-draft.md`, SHA-256 `122963930919073179d4844422d21e85da3a522def3ace723eb992eac43cdade` | owner-frozen, immutable |
| Phase taxonomy | `contracts/p0/runtime/phase-taxonomy.v0-draft.md`, SHA-256 `82aae94c5d124b846f77684e239714d51791115608e786079c4ea4bd4ca05abd` | owner-frozen, immutable |
| Recovery profile | `contracts/p1/kv-recovery-profile.v0-draft.md`, SHA-256 `b363532884d1cae8049ab080d2b85a629f3b33a75f6621788d1e4c8f30737666` | profile-owner frozen |
| Profile approval record | `contracts/p1/kv-recovery-profile-owner-approval.json`, SHA-256 `2831ce52802e7cbe4ec092431c71c18de05491da7ac8d48512014b1d43b3cb0c` | profile-only approval; does not approve this mapping |
| Idle Evidence Contract v4.3 | profiler commit `7e10622eb5755e1af544546e93e3f63a91214ffc`, `docs/idle_evidence_contract.md`, SHA-256 `8edb42b706b6cab14dfde2b109841cb8af090883c9ea86696ee779de21d0c9ed` | interval, clock, canonicalization, completeness, and claim-boundary dependency; still marked proposed in its bytes |
| E3 stream-semantics addendum | `contracts/p1/e3-stream-semantics-addendum.v0-draft.md`, SHA-256 `779faa2ef3f344c739d2092b7d4d250d0a4e3a4c5e76ec04ffcfa0d59ac8eddb` | independent post-v4.3 dependency; never attributed to the v4.3 bytes |

### 2.2 Item 4B activation prerequisite

The separately content-addressed
`contracts/p1/kv-recovery-observer-policy.v0-draft.json`, SHA-256
`fbee3bc4f74b8c5c20e929c4e37596b06b31c1b9cd02517d8461961a8aedf420`, is the candidate source for the pending-container
implementation, its proposed finite capacity, profile record/loss treatment,
connector-result handoff, edge-emitter implementation, and cleanup behavior.
Issue-2 authority may require an applicable owner-approved Item 4B record and
executable conformance before activation, but approval of this mapping neither
approves those implementation choices nor substitutes for their authorities.

### 2.3 Audited source baselines, not immutable semantic dependencies

| Repository | Audited baseline | Meaning |
| --- | --- | --- |
| Runtime | `vLLM-HUST/vllm-hust@f229ba7cad21a4dba58681af6738a9fd947388e2` | static call-site and mapping-review anchor |
| Device plugin | `vLLM-HUST/vllm-ascend-hust@cafad89a5e103f31ea517c1edb56130578c3cd56` | static compatibility and negative-control anchor |

An actual run binds its exact runtime and device-plugin commits through a
complete resolved configuration and joint-admission record and must pass
mapping conformance. A later implementation commit does not require a new
mapping version merely because its Git identity changed. A new mapping version
and issue-2 review are required only if code changes an observation boundary,
identity, edge endpoint, cross-process handoff, D2H/wait mapping, or claim
boundary.

Authenticated source revalidation includes profiler issue #2 comments
`5141244947`, `5157931735`, `5161902781`, `5162001498`, and the authority
request-changes decision `5164544402`. Checked-in fixtures and implementation
hardening are not runtime matched A/B evidence. The E3 rules first summarized
in comment `5162001498` are frozen only by the independent addendum above; the
comment itself and the v4.3 bytes do not substitute for that artifact.

## 3. Independent base-mode blocker

The frozen P0 supported-mode grammar permits only:

```text
kv_cache_mode=disabled|local_homogeneous
```

and explicitly requires `local_homogeneous` to have no KVConnector. The
owner-approved implementation family uses `OffloadingConnector`, so it has no
legal `kv_cache_mode` value under the current P0 bytes. Approving an issue-2
communication code cannot change that separate root-mode grammar.

Consequently this mapping is non-activatable until a separately content-
addressed P0-owner decision does one of the following:

1. freezes an optional base-mode overlay with an exact connector-capable mode,
   validation grammar, and implementation behavior; or
2. freezes a new base trace schema/version carrying that mode.

That P0-owner decision must close two additional grammar points; adding only a
mode string is insufficient. It must explicitly accept that this specialty
profile's **base-operation roster** contains only `h2d_restore`, while the
recovery stream still preserves `d2h_preserve` and `transfer_wait` as
profile-only observations with zero base pairs. It must also accept the H2D
recovery bridge from the just-closed execution epoch to the next admission as
the specialty interpretation of P0's generic "active execution to
communication and communication back to execution" child-edge wording.
Without those decisions, the default paired-operation and generic child-edge
rules would still reject the trace after `kv_cache_mode` gained a connector-
capable value.

The runtime must never report connector-enabled tiering as
`kv_cache_mode=local_homogeneous`, remove the connector from resolved
parameters, or use `communication_mode=none` to pass validation. The current
`runtime_protocol.py` also rejects every non-`none` mode, so later G1 code is
required after all contract gates; its present behavior is not an activation
mechanism.

## 4. Closed mapping roster

| Recovery observation | Base span count | Base edge count | Base status |
| --- | ---: | ---: | --- |
| `h2d_restore` | exactly 1 start/done pair | exactly 3 | required for an accepted positive recovery episode after activation |
| `d2h_preserve` | 0 | 0 | profile-only fact; base emission forbidden in this version |
| `transfer_wait` | 0 | 0 | profile-only process/run fact; request fan-out forbidden in this version |

The only proposed P0 `evidence_source` code in this version is:

```text
issue2:kv-recovery-v1alpha1:h2d_restore
```

The strings ending in `d2h_preserve` and `transfer_wait` remain recovery-side
operation labels, not active P0 evidence codes. Their explicit zero mapping is
part of completeness, not missing instrumentation.

## 5. H2D recovery bridge

### 5.1 Event pair

One successful H2D transfer for an accepted episode emits exactly two P0
`event` records:

| Field | `communication_started` | `communication_done` |
| --- | --- | --- |
| `schema_version` | `rlp.trace/v1alpha1` | same |
| `scope` | `engine_sample` | same |
| `component` | `external_evidence` | same |
| `trace_id` / `lifecycle_id` | exact recovery-profile identity | same |
| `sample_index` | `0` | `0` |
| `preemption_epoch` | positive `recovery_epoch` | same |
| span field | one new `start_span_id`; `end_span_id=null` | matching `end_span_id`; `start_span_id=null` |
| `timestamp_ns` | exact successful worker `submit_load` acceptance observation | exact first matching successful `TransferResult` observation |

Both records have `closing_span_ids=[]`, null handoff/chunk fields, and the
normal parent lifecycle required by P0. Both are emitted by the same rank-0
worker `process_uuid` in the profile's exact `clock_domain_id`. Their metadata
objects have no unknown keys. Start metadata is exactly:

```text
operation="h2d_restore"
direction="h2d"
transfer_id=<profile transfer ID>
block_set_id=<profile block-set SHA-256>
recovery_profile="rlp.kv-recovery/v1alpha1"
recovery_profile_sha256="b363532884d1cae8049ab080d2b85a629f3b33a75f6621788d1e4c8f30737666"
communication_mapping="issue2:kv-recovery-v1alpha1"
communication_mapping_sha256=<final SHA-256 of this mapping artifact>
rank=0
```

Done metadata has those same values plus positive uint64 `bytes_moved`. Every
string and the complete object obey the frozen P0 scalar and 1024-byte metadata
bounds. The base event IDs are copied into the corresponding profile
`restore_start` and `restore_done` records; matching text or timestamps alone
are insufficient.

For interval use, `done.timestamp_ns` must be strictly greater than
`start.timestamp_ns`. Equal host observations remain diagnostic point evidence
in the recovery profile and cannot become a zero-length communication span.

### 5.2 Exact H2D endpoint handoff and emitter state machine

This section freezes semantic identity, endpoint handoff, emitter ownership,
and fail-closed behavior only. Pending-container fields, its admitted finite
bound, record-sequence/loss-ledger implementation, capacity failure code,
result transport, cleanup implementation, and executable runtime attestation
belong to the separately approved Item 4B dependency in section 2.2. This
mapping does not itself freeze
`max_pending_h2d_contexts_per_process=4096` or assign
`serialization_failure` to observer-context admission failure.

#### 5.2.1 Endpoint origin and ownership

| Endpoint | Origin and exact selection | Event component | Event-emitting process |
| --- | --- | --- | --- |
| `preempted(e)` | The already-emitted EngineCore base event that closed the exact lifecycle's epoch `e`; its event ID is captured at emission, never recovered by request or time lookup. | `engine_core` | EngineCore process |
| `communication_started(e+1)` | The rank-0 worker observation immediately after matching backend `submit_load` returns accepted for the exact H2D attempt. | `external_evidence` | rank-0 transfer-worker process |
| `communication_done(e+1)` | The first matching successful raw `TransferResult`, with strictly later host timestamp and positive bytes. | `external_evidence` | the same rank-0 worker process as the start |
| `admission_started(e+1)` | The first real EngineCore base admission event for the same request/lifecycle/epoch after the exact H2D receipt is accepted and after the first matching successful profile `scheduler_wakeup`/promotion. An earlier selection attempt is ineligible. | `engine_core` | EngineCore process |

The communication pair has one fresh worker-created span ID. Both events have
the same trace, lifecycle, recovery epoch, worker `process_uuid`, rank, clock
domain, transfer ID, and block-set ID. Done time is strictly greater than
start time and `bytes_moved` is a positive uint64.

#### 5.2.2 Exact sidecar, pending, and receipt identities

For one H2D load, the scheduler-to-worker connector envelope is keyed by the
exact `connector_job_id` and carries one immutable recovery context containing:

- profile ID/SHA, mapping ID/SHA, and admitted resolved-configuration ID;
- `run_id`, `trace_id`, `engine_lifecycle_id`, and exact runtime request ID;
- positive `recovery_epoch=e+1` and matching `episode_id`;
- `base_preempted_event_id`, copied from the actual emitted `preempted(e)`;
- `operation=h2d_restore`, canonical `block_set_id`, and canonical logical
  blocks.

The worker allocates one process-scoped `transfer_id` before backend
submission. Only after exact submission acceptance may it construct
`communication_started`. An admitted Item 4B pending entry contains at least
the context above plus `connector_job_id`, `transfer_id`,
`communication_started_event_id`, worker process/rank/clock identity, start
timestamp, and an unconsumed state. Request text, timestamps, job-number
proximity, stage adjacency, or matching block coordinates cannot substitute
for any field.

Only the first valid successful completion returns a worker-to-EngineCore
receipt. It carries the same content-addressed binding and recovery identity;
the exact connector job, transfer, and block-set IDs; worker process/rank/world
and clock identity; exact `communication_done_event_id`; exact restore-done
profile record ID; completion timestamp; and positive bytes. The connector
transports the receipt unchanged. EngineCore accepts it only while that load
job and episode are live and every field equals scheduler-owned state.
Truncation, absence, mutation, stale status, or an unprovable handoff makes the
affected formal evidence incomplete.

#### 5.2.3 Exactly three edges and concrete emitters

1. `preempted(e) -> communication_started(e+1)` is
   `data_dependency / issue2:kv-recovery-v1alpha1:h2d_restore`. The rank-0
   worker issue-2 adapter emits it in the worker shard only after it possesses
   both the exact propagated preempted ID and newly allocated start ID.
2. `communication_started(e+1) -> communication_done(e+1)` is
   `program_order / instrumented_execution_context`. The same worker adapter
   emits it only after atomically consuming the exact pending entry and
   successfully constructing the matching done endpoint. Process equality,
   polling order, and timestamps do not justify it.
3. `communication_done(e+1) -> admission_started(e+1)` is
   `data_dependency / issue2:kv-recovery-v1alpha1:h2d_restore`. The EngineCore-
   side issue-2 adapter emits it in the EngineCore shard only after accepting
   the exact receipt, observing matching successful scheduler wakeup, and
   receiving the exact event ID from the real admission emitter.

An edge record is attempted only after both endpoint event IDs are explicitly
known. Each `(from_event_id, to_event_id, edge_kind, evidence_source)` tuple is
consumed at most once. Edge records have no component field; event components
and concrete edge-record process ownership above are normative.

#### 5.2.4 Atomic consumption and fail-closed transitions

The admissible state sequence is:

```text
SIDECAR_READY -> START_RECORDED -> COMPLETION_CONSUMED
  -> RECEIPT_ACCEPTED -> ADMISSION_EDGE_RECORDED
```

- A failed or rejected backend submission produces no base communication event
  or issue-2 edge.
- Only the first exact successful raw completion may atomically consume the
  start. Duplicate, retry, already-consumed, unknown/stale job, wrong operation
  or direction, wrong request/lifecycle/epoch/episode/transfer/block set,
  foreign run/process/clock, nonpositive bytes, or nonpositive duration emits
  no new communication event or edge.
- A missing sidecar field or endpoint ID emits no edge. An already-attempted
  lost record keeps its `record_seq` consumed under the separately admitted
  Item 4B loss ledger; later records cannot repair it.
- A second preemption or effective terminal before done consumes and
  invalidates the open worker context. A terminal, new preemption, epoch
  replacement, or request cleanup after receipt but before qualifying
  admission consumes the EngineCore return context. No later event or edge is
  backfilled, and a communication span never crosses preemption or terminal.
- Duplicate receipts or duplicate qualifying admissions never emit another
  edge. Item 4B must provide an explicit EngineCore-to-worker episode
  invalidation handoff, or an executable mechanism with the same guarantee,
  before activation.
- Exhausting separately admitted prepared-transfer or pending-context capacity
  never rejects, delays, cancels, or resizes the real transfer. Before
  `START_RECORDED`, it admits no formal H2D context, emits no new base pair or
  edge, consumes the applicable attempted profile `record_seq`, and uses only
  the independently owner-approved failure code and loss semantics.
- Receipt append/aggregation exhaustion is a later failure: start, done, and
  the first two edges may already be immutable. The implementation retains
  every record already written without retraction, rewrite, or duplication;
  emits no receipt and no third done-to-admission edge; never backfills or
  infers the missing handoff; consumes the exact profiler loss `record_seq`;
  and rejects the affected trace. Item 4B must require a CPU test for this
  timing. An implementation may pre-reserve future receipt capacity before
  start only if it proves late exhaustion unreachable for every admitted
  context; a violated reservation still cannot erase earlier records.

#### 5.2.5 Normalizer prohibition and base-DAG relation

The normalizer only validates explicitly written events and edges. It never
creates, selects, repairs, or deduplicates an H2D endpoint or edge from request
identity, timestamp or file order, any global/per-process `record_seq`, stage
or job-number adjacency, common process/rank/clock/direction/block set, or the
existing `preempted -> requeued` branch. It must not invent
`requeued -> communication_started`, choose a nearby admission, or treat a
profile association as a base edge. Missing endpoint, edge, handoff, or
qualifying wakeup/admission relation rejects the affected trace.

The profile relation remains exactly
`base.preemption_epoch + 1 == recovery_epoch`. Existing P0
`preempted -> requeued` and queue/admission edges remain required. The branches
converge without a timestamp-derived edge and the full same-trace graph remains
acyclic. This specialty bridge never moves base preemption, requeue, admission,
prefill, or decode boundaries. Its required order is:

```text
preempted(e) <= requeued(e+1) <= communication_started(e+1)
  < communication_done(e+1) <= scheduler_wakeup(e+1)
  <= admission_started(e+1) <= resumed(e+1)
```

The profile-only scheduler-wakeup point selects the return endpoint but adds no
base event or edge.

## 6. D2H closed negative mapping

The audited runtime constructs stores for scheduled request blocks, defers
submission until a later engine step, and may complete them asynchronously.
The transfer can be proactive, can outlive the source step, and has no stable
same-request base event whose execution is guaranteed to wait for completion.
A later block-reuse or preemption fence does not retroactively make the
original submission a child of that later event.

Therefore v1 records the exact D2H submit/done, bytes, device duration when
available, logical blocks, request/lifecycle, and transfer identity only in
`rlp.kv-recovery/v1alpha1`. It emits no base `communication_started`,
`communication_done`, or issue-2 edge. The normalizer must not invent a return
edge to `preempted`, `requeued`, admission, or a nearby compute event.

Every admitted D2H profile submit still has exactly one matching successful
done with strict positive host duration and bytes and the identical transfer,
request/lifecycle, process/rank, direction, and logical block set. Profile
close may leave no submitted D2H orphaned or open; retry, failure, duplicate,
identity drift, or an unresolved completion rejects the affected formal
evidence even though no base span is emitted.

If issue-2 authority requires D2H in the base DAG, this candidate must be
replaced by a new mapping/profile version that freezes an asynchronous/detached
span relation. It cannot be repaired by timestamp adjacency.

## 7. Transfer-wait closed negative mapping

`OffloadingWorker.wait(job_ids)` is one process-local blocking call. Its job
set may combine stores from multiple requests and traces or block-reallocation
fences. The approved `wait_set_chunk` is correspondingly run/process-scoped,
but it carries one observation timestamp and exact membership, not a paired
process-scope interval schema.

Accordingly v1:

- preserves the complete sorted `transfer_id` membership through
  `wait_set_chunk` records;
- assigns every chunk of one wait-set observation the same timestamp captured
  immediately before entry to `OffloadingWorker.wait(job_ids)`; this is a
  point marker, not a paired interval boundary;
- resolves and freezes the exact member set before entry, invokes the existing
  wait unchanged, and enqueues the contiguous chunks only after normal return;
  an exception, missing return, member drift, or mixed chunk timestamp rejects
  the observation rather than fabricating completion;
- emits zero base communication events and edges for the wait;
- forbids cloning the same call into one span per member request;
- forbids selecting one arbitrary request as its parent; and
- treats the single wait-entry observation only as a point marker; this schema
  has no wait-duration value to compare with zero.

`wait_set_id` remains only the membership digest. Offline normalization derives
`wait_call_observation_id` as the unique `record_id` of that contiguous
group's `chunk_index=0` record; it is not a new wire field. All chunks in the
group have one `wait_set_id`, `chunk_count`, and wait-entry timestamp and use
contiguous indexes `0..chunk_count-1`. A later call with the same membership is
therefore a distinct observation because it has a different first-chunk record
ID. Missing, interleaved, duplicated, or inconsistent chunks fail evidence
closed rather than being collapsed across calls.

This mapping does not support a formal transfer-wait duration or a causal idle
claim. A paired process-scope wait interval requires a new profile/schema
version and a new owner digest. Scheduler `restore_done -> scheduler_wakeup`
and later recovery gaps remain measurable from the approved request profile;
they must not be relabeled as this worker wait.

## 8. Measurement semantics and duplicate suppression

The P0 recovery span is host lifecycle/dependency evidence. It is not by
itself a device-clock productive interval and does not establish hardware idle
or copy/compute overlap. `TransferResult.transfer_time` is a positive duration,
not a positioned device timestamp interval.

When an Ascend profiler capture is separately available, Idle Evidence
Contract v4.3 applies only to its frozen interval, clock, canonicalization,
completeness, and claim-boundary rules:

- `MEMCPY`, `MEMCPY_ASYNC`, and `SDMA` are
  `productive_data_move`, retaining H2D/D2H and sync/async granularity;
- `COMMUNICATION_OP` is canonical when a valid match exists; linked `TASK`
  rows remain supporting evidence;
- matching requires compatible run/database scope, device, unambiguous exact
  connection identity when available, time, and metadata;
- an uncertain duplicate is reported as ambiguous and is never silently
  merged; and
- host/device overlap or delay claims require its marker calibration,
  holdout error, and robust-window rules.

The separately hashed E3 addendum, not the v4.3 bytes, freezes the post-v4.3
stream rules: scan completeness is computed independently per device before
run aggregation; stream `0xFFFFFFFF` is unassigned, creates no fabricated
timeline, and makes that device's `observed_universe_scan_complete=false`;
legal zero-duration wait, capture-control, record, and runtime-control rows are
point markers only; those points create neither a zero-length interval nor
interval-bearing stream-universe membership; and zero-duration productive or
unknown observations are invalid input.

The E3 approval decision explicitly includes the intersection where a legal
zero-duration point carries `0xFFFFFFFF`: it remains point-only but still makes
the affected device incomplete. The audited PR #15 implementation baseline
does not yet implement that intersection and therefore cannot be admitted as
E3 conformance until it changes and passes the addendum's case 4. Issue-2
approval of this mapping accepts that fail-closed semantic requirement, not a
claim that the engineering baseline already satisfies it.

One runtime source operation maps to one recovery transfer identity and, only
for H2D, one base span. The same source must not become multiple productive
device intervals because it appears in several profiler tables. Without an
explicit bridge from `transfer_id` to a unique device operation, runtime and
device observations remain separate evidence rather than a guessed join.

Admission keeps these states separate rather than deriving one from another:

- `runtime_mapping_status`;
- `collection_status`;
- per-device and run-level `observed_universe_scan_complete`;
- `alignment_status`;
- `canonicalization_status`; and
- `analysis_status`.

Base/profile events on the same host and canonical `CLOCK_MONOTONIC` domain
need no clock alignment. Device projection or any cross-domain comparison
still requires v4.3 calibration. A complete runtime mapping does not imply a
complete device collection, and a positive `device_duration_ns` cannot
substitute for positioned device start/end timestamps.

## 9. Completeness and rejection

A mapping-complete positive episode requires:

1. the exact approved recovery-profile digest and a complete paired base/profile
   process roster;
2. one valid H2D start/done pair, the exact three-edge roster, positive bytes,
   strict positive host duration, and one stable transfer/block/request/epoch
   identity;
3. all applicable profile-only D2H and wait-set facts with no profile loss,
   without any forbidden base fan-out;
4. no retry, transfer failure, mixed clock domain, unresolved endpoint,
   duplicate span/edge, graph cycle, or communication across another
   preemption/terminal;
5. a separately owner-ratified Item 4B policy, executable conformance for its
   exact pending/receipt/emitter/loss/cleanup behavior, and an admitted finite
   capacity/failure-code source;
6. a separately frozen connector-capable base mode and its P0-owner approval;
7. this mapping's final digest and separate issue-2-authority approval; and
8. complete configuration, joint admission, process receipts, and run manifest
   binding the actual runtime/device commits plus the semantic dependency,
   profile, mapping, Item 4B, and base-mode digests.

Any violation rejects the entire formal trace. Serving remains fail-open;
evidence fails closed. Profile-only diagnostic records may be retained but do
not activate `communication_mode=issue2:kv-recovery-v1alpha1`.

Every conclusion is kept in four non-interchangeable layers: raw observation,
normalized structure, causal hypothesis, and matched validation. Profile/base
rows and their exact span/edge/membership structure establish only the first
two. A possible restore or wait contribution is a hypothesis; only a matched
runtime A/B at the same workload and collection boundary can validate it.

## 10. Claim boundary

Even after activation, this mapping proves only that one instrumented runtime
dependency chain was captured. It does not prove device idle, that a visible
wait caused a gap, copy/decode overlap, a performance improvement, or M0. Those
claims still require the exact issue-2 measurement rules, collection
completeness, matched runtime A/B, and the later benchmark gates.

## 11. Proposed authority approval items

Issue-2 authority must accept or replace each item while citing the final
mapping SHA-256:

1. mapping ID, immutable semantic dependency digests, separate Item 4B policy
   candidate digest, and audited-source-baseline classification;
2. the independent P0/base-mode blocker and non-activation rule;
3. the asymmetric closed roster: H2D `1 span + 3 edges`, D2H `0 + 0`, wait
   `0 + 0`;
4. two authority-separated subitems:
   - **4A, issue-2 authority:** `h2d_restore` subtype, one span/three explicit
     edges, exact request/lifecycle/epoch/transfer/block identity, positive
     duration/bytes, concrete endpoint handoff and emitters, prohibition on
     timestamp-derived edges, incomplete identity/handoff fail-closed, and no
     automatic device-idle or performance conclusion;
   - **4B, separate profile/P0/runtime authorities:** pending fields/container,
     specific per-process capacity, profile `record_seq` and loss ledger,
     full-table failure code, runtime sidecar/result handoff, emitter
     implementation, terminal/preemption invalidation, and close cleanup.
     Issue-2 approval accepts only that an applicable owner-approved and
     executable 4B is mandatory before activation; it does not approve 4B.
5. D2H profile-only evidence, zero base span/edge mapping, and prohibition on
   inferred request return edges;
6. transfer-wait as a process/run point with one exact member relation, zero
   base span/edge mapping, and prohibition on request fan-out or fabricated
   duration;
7. separate acceptance of the v4.3 interval/clock/canonicalization/claim
   dependency and the independent E3 addendum's unassigned-stream and
   zero-duration point-only semantics, including the sentinel-plus-point
   fail-closed intersection and the recorded PR #15 conformance gap, together
   with completeness, duplicate suppression, and fail-closed behavior; and
8. resolved-run source binding, the exact rule for when a source change needs
   a new mapping, and the requirement that any D2H base span or paired process-
   wait interval use a new content-addressed version rather than altering these
   bytes.

Authority approval freezes only this mapping. It does not approve a base-mode
overlay, resolved benchmark configuration, G1 implementation, NPU work,
service launch, experiment, or performance claim.
