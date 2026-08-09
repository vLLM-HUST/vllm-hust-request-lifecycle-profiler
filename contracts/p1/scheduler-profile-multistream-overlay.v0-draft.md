# Scheduler Profile Multi-Stream Shard Overlay — Architecture Review Candidate

- Status: `architecture_review_candidate`
- Evidence status: `NOT_IMPLEMENTED`
- Proposed overlay ID: `rlp.trace-sharding/multi-profile-v1alpha1`
- Base lifecycle schema: `rlp.trace/v1alpha1`
- Proposed scheduler profile: `rlp.scheduler/v1alpha1`
- Decision-date basis: `2026-08-09`

This document proposes one narrowly scoped revision to the owner-frozen P0
runtime contract. It does not edit or silently reinterpret the approved P0
bytes. The approved P0 contract remains identified by SHA-256
`122963930919073179d4844422d21e85da3a522def3ace723eb992eac43cdade`
until this overlay, a complete downstream wire contract, and a new owner
approval are content-addressed and ratified.

The proposed revision is:

> Each `(process_uuid, profile_stream)` pair owns one append-only shard and one
> monotonically increasing data-record sequence. No two processes or profile
> streams append to the same shard.

This replaces only the P0 invariant that says each process owns one shard and
one data-record sequence. Every other P0 invariant remains unchanged unless a
later version names and approves an additional replacement.

## 1. Motivation and boundary

`rlp.trace/v1alpha1` and the proposed `rlp.scheduler/v1alpha1` have different
record vocabularies, capacity envelopes, completeness summaries, and evidence
consumers. Appending scheduler records to a lifecycle shard would mutate the
frozen lifecycle wire schema. Giving the scheduler profile an unrelated
logger would instead duplicate failure semantics and lose the common process
identity needed for audit.

The multi-stream model preserves one exporter framework and one process
identity while giving each approved profile an independent wire and ledger
boundary.

This overlay does not:

- approve `rlp.scheduler/v1alpha1` wire bytes;
- authorize runtime instrumentation;
- change lifecycle event, edge, clock, privacy, or phase semantics;
- permit more than one shard for the same `(process_uuid, profile_stream)`;
- permit profile rotation or segmentation in this version;
- make scheduler-only diagnostic output formal lifecycle evidence;
- authorize an NPU run, performance claim, or mechanism experiment.

## 2. Identity model

### 2.1 `process_uuid`

`process_uuid` continues to identify one runtime process invocation and keeps
the frozen P0 representation of 32 lowercase hexadecimal characters.

The exporter framework MUST generate or acquire `process_uuid` once for the
process and share that exact value with every enabled profile stream. A profile
MUST NOT generate a second value and describe it as the same process.

Across process restarts, a new `process_uuid` is required even when PID,
engine role, rank, and run identity are unchanged.

### 2.2 `profile_stream`

`profile_stream` identifies one approved wire/ledger namespace. The initial
roster is:

| `profile_stream` | Wire dependency | Purpose |
| --- | --- | --- |
| `lifecycle` | `rlp.trace/v1alpha1` | Owner-frozen request lifecycle trace |
| `scheduler` | proposed `rlp.scheduler/v1alpha1` | Scheduler semantic evidence |

The final wire contract MUST freeze the encoded representation and filename-
safe slug for each value. An unknown stream is unsupported and cannot be
promoted by treating it as lifecycle or scheduler data.

### 2.3 Shard and sequence scope

For each enabled `(process_uuid, profile_stream)` pair:

- exactly one append-only shard is created;
- exactly one data-record sequence starts at zero;
- `record_seq` is allocated before validation, serialization, or enqueue;
- sequence gaps are covered by that stream's own loss ledger;
- record IDs are unique within the stream and MUST include or be resolved with
  the stream scope;
- start, summary, content digest, and committed receipt belong only to that
  stream;
- another stream may use the same numeric `record_seq` without collision
  because `profile_stream` is part of the full identity.

The complete record key is logically:

```text
(process_uuid, profile_stream, record_seq)
```

The future wire contract MAY encode `profile_stream` directly in every record
or bind it immutably through the shard start record and manifest. It MUST NOT
leave the scope inferable only from a user-chosen filename.

## 3. Writer ownership and physical isolation

One process-local exporter owner MAY manage multiple approved profile-stream
queues and writer states. For each stream it MUST preserve independently:

- bounded non-waiting producer behavior;
- data and reserved-control capacity;
- attempted/written/dropped accounting;
- loss intervals;
- writer failure state;
- close outcome;
- content digest;
- committed-shard receipt.

Lifecycle and scheduler records MUST NOT share a `record_seq`, loss ledger, or
summary merely because their writers are managed by the same owner.

The lifecycle shard's existing path and bytes remain unchanged. The scheduler
wire contract MUST define a distinct create-exclusive, mode-`0600` path. A path
collision, cross-stream append, or a shard whose stream identity disagrees
with its manifest fails the affected profile closed for evidence while serving
continues fail-open.

## 4. Activation and disabled behavior

Each stream is default-off according to its own approved configuration.

When scheduler profiling is disabled, it MUST create no scheduler shard, queue,
writer activity, record construction, or scheduler-specific clock sampling.
This requirement does not disable lifecycle tracing when lifecycle tracing is
independently enabled.

Scheduler-only output MAY be retained as explicitly labelled diagnostic
evidence. Formal scheduler-to-request attribution requires the complete
lifecycle and scheduler roster declared by the scheduler profiler contract.

## 5. Completeness and paired admission

Shard completeness remains evaluated per `(process_uuid, profile_stream)`.
A complete lifecycle shard cannot repair an incomplete scheduler shard, and a
complete scheduler shard cannot repair an incomplete lifecycle shard.

The experiment manifest MUST predeclare the logical process/profile roster,
for example:

```text
(engine_core, rank=0, lifecycle)
(engine_core, rank=0, scheduler)
```

After process start, a launch/binding receipt maps every logical roster entry
to its actual `process_uuid` and shard path. Post-processing MUST NOT discover
the expected set by globbing only the shards that happened to exist.

Formal scheduler-profiler evidence is jointly admitted only when every
required lifecycle and scheduler shard and receipt is complete. Individually
valid shards remain immutable diagnostic artifacts; a missing paired shard
does not authorize fabrication, timestamp inference, or deletion of the valid
artifact.

## 6. Boundedness policy

This overlay selects one shard per `(process_uuid, profile_stream)` for the
initial scheduler profile. Rotation and segmentation are not part of the
proposed v1 model.

The downstream wire contract MUST separately prove:

1. queue capacity from peak producer rate, maximum records per cycle, maximum
   approved writer-service gap, batch policy, and reserved-control demand;
2. queued-byte capacity from the maximum encoded record size;
3. total artifact bounds from maximum run duration/cycles, maximum records per
   cycle, maximum encoded bytes, and a disk-space preflight;
4. close/drain bounds and failure behavior.

Total records produced over a run MUST NOT be confused with instantaneous
in-memory queue capacity. If the approved single-shard artifact or queue bound
cannot cover a proposed run, that run is unsupported for formal evidence. A
later segmented design requires a new overlay version and owner approval.

## 7. Compatibility and migration

Legacy `rlp.trace/v1alpha1` readers continue to consume the lifecycle shard and
need not open the scheduler shard. Scheduler-aware readers MUST validate the
overlay and scheduler-profile versions before combining streams.

The normalizer MUST reject:

- multiple shards for one `(process_uuid, profile_stream)`;
- one shard containing records from multiple profile streams;
- a scheduler shard using a lifecycle record sequence or summary;
- a manifest that maps one logical stream instance to multiple shards;
- cross-stream ID resolution that omits `profile_stream` scope;
- a scheduler/lifecycle pair with different runtime process identity.

## 8. Approval and implementation gate

Before this overlay can become authoritative, owner review MUST approve exact
content digests for:

1. this overlay;
2. the completed scheduler wire contract produced after PR-I0;
3. the exact representation and scope of `profile_stream`;
4. the lifecycle-preserving scheduler shard path convention;
5. per-stream queue, byte, control-reserve, and close limits;
6. the paired manifest/receipt and completeness rules;
7. compatibility tests proving unchanged lifecycle bytes and disabled behavior.

Architecture review of this file does not amend the owner-frozen P0 contract.
No runtime implementation may claim this overlay is active until the new
digest-bound owner approval exists.
