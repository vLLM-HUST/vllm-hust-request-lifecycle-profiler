# KV-Recovery Communication Mapping v0 Draft

- Proposed mapping ID: `issue2:kv-recovery-v1alpha1`
- Review status: `issue2_authority_review_required`
- Activation status: `BLOCKED_BY_BASE_MODE_GRAMMAR_AND_AUTHORITY`
- Evidence status: `NOT_M0_PROVEN`
- Runtime implementation status: `NOT_STARTED`

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

## 2. Exact dependencies

| Dependency | Content identity | Status |
| --- | --- | --- |
| Minimum runtime contract | `contracts/p0/runtime/minimum-runtime-contract.v0-draft.md`, SHA-256 `122963930919073179d4844422d21e85da3a522def3ace723eb992eac43cdade` | owner-frozen, immutable |
| Phase taxonomy | `contracts/p0/runtime/phase-taxonomy.v0-draft.md`, SHA-256 `82aae94c5d124b846f77684e239714d51791115608e786079c4ea4bd4ca05abd` | owner-frozen, immutable |
| Recovery profile | `contracts/p1/kv-recovery-profile.v0-draft.md`, SHA-256 `b363532884d1cae8049ab080d2b85a629f3b33a75f6621788d1e4c8f30737666` | profile-owner frozen |
| Profile approval record | `contracts/p1/kv-recovery-profile-owner-approval.json`, SHA-256 `2831ce52802e7cbe4ec092431c71c18de05491da7ac8d48512014b1d43b3cb0c` | profile-only approval; does not approve this mapping |
| Idle evidence semantics | profiler commit `7e10622eb5755e1af544546e93e3f63a91214ffc`, `docs/idle_evidence_contract.md` Draft v4.3, SHA-256 `8edb42b706b6cab14dfde2b109841cb8af090883c9ea86696ee779de21d0c9ed` | normative measurement dependency, still marked proposed in its bytes |
| Runtime | `vLLM-HUST/vllm-hust@f229ba7cad21a4dba58681af6738a9fd947388e2` | audited source anchor |
| Device plugin | `vLLM-HUST/vllm-ascend-hust@cafad89a5e103f31ea517c1edb56130578c3cd56` | audited source anchor |

Authenticated source revalidation includes profiler issue #2 comments
`5141244947`, `5157931735`, `5161902781`, and `5162001498`. The last two
comments preserve the same boundary: checked-in measurement fixtures and
implementation hardening are not runtime matched A/B evidence. Comment
`5162001498` also requires per-device scan completeness, forbids an unassigned-
stream sentinel from fabricating a timeline, and treats legal zero-duration
wait/control/record observations as point markers rather than intervals.

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

### 5.2 Exactly three edges

The runtime emits these three and no duplicate edges for the H2D pair:

1. closing-epoch base `preempted(e)` to
   `communication_started(e+1)`: `data_dependency` with
   `issue2:kv-recovery-v1alpha1:h2d_restore`;
2. `communication_started(e+1)` to `communication_done(e+1)`:
   `program_order` with `instrumented_execution_context`; and
3. `communication_done(e+1)` to the matching next-epoch
   `admission_started(e+1)`: `data_dependency` with
   `issue2:kv-recovery-v1alpha1:h2d_restore`.

The internal `program_order / instrumented_execution_context` edge is not
justified by process equality, polling order, or timestamp order. A later G1
adapter must allocate `transfer_id` before accepted submission and insert one
bounded pending-context entry containing the exact start event ID, request,
lifecycle, recovery epoch, block set, connector job ID, process/rank, and clock
domain. The first matching successful raw `TransferResult` atomically consumes
that entry, emits `communication_done`, and then emits the internal edge. An
unknown, duplicate, failed, mismatched, already-consumed, or capacity-rejected
context cannot emit the pair or edge and fails the affected evidence closed.
The process-local pending table has the exact hard limit
`max_pending_h2d_contexts_per_process=4096`, in addition to the approved
per-lifecycle transfer limit, and is drained/rejected at profile close. If the
observer table is full, the real connector submission and serving path proceed
unchanged. Capacity exhaustion is one attempted profile `transfer_event`
construction: it consumes the next profile `record_seq`, emits no corresponding
base pair or edge, and opens or extends the exact `serialization_failure` loss
interval required by approved-profile sections 6.2 and 6.7. A
`queue_overflow` reason or log-only diagnostic is forbidden for this case. The
affected formal evidence fails closed, but the adapter must never reject,
delay, cancel, or resize the real KV transfer to create trace capacity. CPU
tests must prove this explicit propagation, process bound, deterministic loss,
and fail-open serving behavior before runtime wiring can pass G1; the current
source does not already provide it.

Here the profile relation is exactly `base.preemption_epoch + 1 ==
recovery_epoch`. The existing P0 `preempted -> requeued` and queue/admission
edges remain required. The two branches converge at admission without adding a
timestamp-derived `requeued -> communication_started` edge. All endpoints are
same-trace, resolve explicitly, and must leave the full graph acyclic.

This is a recovery bridge authorized only by the optional mapping; it does not
move the base preemption, requeue, admission, prefill, or decode boundaries.
The H2D span begins after preemption and may not remain open across another
preemption or terminal.

The target is the first `admission_started(e+1)` after the first successful
profile `scheduler_wakeup`/promotion observation for this exact transfer and
episode, never an earlier queue-selection attempt while the load was pending.
The complete required order is:

```text
preempted(e) <= requeued(e+1) <= communication_started(e+1)
  < communication_done(e+1) <= scheduler_wakeup(e+1)
  <= admission_started(e+1) <= resumed(e+1)
```

The scheduler-wakeup point is profile-only; it constrains endpoint selection
but does not add a new P0 event or edge.

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

When an Ascend profiler capture is separately available, Draft v4.3 applies:

- `MEMCPY`, `MEMCPY_ASYNC`, and `SDMA` are
  `productive_data_move`, retaining H2D/D2H and sync/async granularity;
- `COMMUNICATION_OP` is canonical when a valid match exists; linked `TASK`
  rows remain supporting evidence;
- matching requires compatible run/database scope, device, unambiguous exact
  connection identity when available, time, and metadata;
- an uncertain duplicate is reported as ambiguous and is never silently
  merged; and
- host/device overlap or delay claims require the frozen marker calibration,
  holdout error, and robust-window rules.

Scan completeness is computed independently per device before run-level
aggregation. An unassigned-stream sentinel contributes no fabricated timeline
interval and forces `observed_universe_scan_complete=false` for that device and
therefore for the run. Legal zero-duration wait/control/record observations
remain point markers only; a zero-duration H2D/D2H productive operation or
unknown interval is invalid input.

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
5. a separately frozen connector-capable base mode and its P0-owner approval;
6. this mapping's final digest and separate issue-2-authority approval; and
7. complete configuration, process receipts, and run manifest binding the
   runtime/device/profile/mapping/base-mode digests.

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

1. mapping ID and exact dependency digests;
2. the independent P0/base-mode blocker and non-activation rule;
3. the asymmetric closed roster: H2D `1 span + 3 edges`, D2H `0 + 0`, wait
   `0 + 0`;
4. the exact H2D events, metadata, epoch relation, and edge grammar;
5. prohibition on D2H return-edge inference and process-wait request fan-out;
6. v4.3 clock, evidence, canonicalization, zero-duration, and forbidden-claim
   semantics;
7. completeness, duplicate suppression, and fail-closed behavior; and
8. the requirement that any D2H base span or paired process-wait interval use a
   new content-addressed version rather than altering these bytes.

Authority approval freezes only this mapping. It does not approve a base-mode
overlay, resolved benchmark configuration, G1 implementation, NPU work,
service launch, experiment, or performance claim.
