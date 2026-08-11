# Multi-Profile Shard Overlay — Owner Review Candidate

- Status: `owner_review_candidate`
- Evidence status: `NOT_IMPLEMENTED`
- Overlay ID: `rlp.trace-sharding/multi-profile-v1alpha1`
- Supersedes candidate: `scheduler-profile-multistream-overlay.v0-draft.md`
- Scheduler wire: `rlp.scheduler/v1alpha1`

This candidate amends exactly one owner-frozen P0 invariant after explicit
digest approval:

> Each `(process_uuid, profile_stream)` pair owns one append-only shard and one
> monotonically increasing data-record sequence. No two processes or streams
> append to the same shard.

It does not edit the approved `rlp.trace/v1alpha1` bytes or the already frozen
`rlp.kv-recovery/v1alpha1` bytes. Until the owner approves this file together
with the scheduler contract and configuration, the original P0 invariant
remains authoritative.

## 1. Stream roster and representation

The closed initial roster is:

| `profile_stream` | Wire authority | Physical path |
| --- | --- | --- |
| `lifecycle` | `rlp.trace/v1alpha1` | unchanged `<base>.rlp.<process_uuid>.jsonl` |
| `scheduler` | `rlp.scheduler/v1alpha1` | `<base>.rlp-scheduler.<process_uuid>.jsonl` |
| `kv_recovery` | `rlp.kv-recovery/v1alpha1` | unchanged `<base>.rlp-kv-recovery.<process_uuid>.jsonl` |

Every scheduler record carries exact field `profile_stream="scheduler"`.
Lifecycle and KV-recovery records remain byte-for-byte compatible and do not
gain a new field. Their stream scope is bound by the manifest entry and their
existing start/profile record. A filename alone is never the authority.

An unknown stream, a stream/path disagreement, or treating one stream as
another is unsupported. Stream slugs are exactly `lifecycle`, `scheduler`, and
`kv-recovery` in paths; the logical KV stream value remains `kv_recovery`.

## 2. Shared process identity

`process_uuid` retains the P0 representation of 32 lowercase hexadecimal
characters. It is generated once per process invocation and shared by every
enabled stream in that process. A restart always receives a new UUID even when
PID, rank, device, or role is unchanged.

The complete scheduler record key is:

```text
(process_uuid, profile_stream="scheduler", record_seq)
```

The same numeric `record_seq` may exist in another stream because the stream is
part of the key. Cross-stream ID resolution that omits the stream is invalid.

## 3. Independent writer state

One process-local exporter owner may manage multiple streams, but each enabled
stream has independent:

- bounded data and reserved-control capacity;
- record and control sequence allocation;
- loss intervals and failure state;
- start and summary records;
- content digest and close result;
- committed-shard receipt and create-exclusive mode-`0600` descriptor.

Queues, byte budgets, summaries, and loss ledgers cannot be borrowed or merged
across streams. A full scheduler queue never delays or drops lifecycle/KV data,
and vice versa. Every stream failure stays serving fail-open and makes only the
affected evidence stream fail closed; joint admission then fails because its
required pair is incomplete.

## 4. Exact scheduler limits

The scheduler stream uses the exact limits in
`scheduler-profile-config.v1alpha1.json`: 1024 data records, 64 reserved
loss-interval records, dedicated start/summary paths, 8192 encoded bytes per
record, 8,912,896 total queued bytes,
128 records/524,288 bytes per writer batch, 100-ms target write interval,
2-second maximum admitted service gap, and one 5-second close deadline.

Lifecycle and KV-recovery limits and wire paths do not change. The scheduler
single-shard artifact is admitted only when the configured 2,441,699,328-byte
disk preflight passes. Rotation, segmentation, and more than one shard for one
`(process_uuid, profile_stream)` are outside this overlay.

## 5. Disabled behavior

Each stream is independently default-off. With scheduler profiling disabled:

- no scheduler shard, queue, descriptor, writer state, or receipt exists;
- no scheduler record or fixed constraint summary is constructed;
- no scheduler-specific clock syscall or bridge sample occurs;
- lifecycle and KV-recovery behavior is unchanged.

Enabling the scheduler stream does not implicitly enable either other stream.
Formal scheduler-profiler collection predeclares and admits its required paired
roster separately.

## 6. Manifest, receipt, and completeness

Before launch the experiment manifest declares every logical tuple of
`(engine role, rank, device, profile_stream)`. After launch, an independently
captured binding maps each tuple to exactly one `process_uuid`, strict shard
path, schema/config digests, and immutable successful close receipt. Globbing
observed files cannot define or shrink the expected roster.

Shard completeness is per tuple. Joint scheduler-profiler evidence requires:

```text
all predeclared lifecycle shards and receipts complete
AND all predeclared scheduler shards and receipts complete
AND every lifecycle/scheduler pair shares the receipted process invocation
AND every join-bearing executor process has one approved exact
    runtime-to-profiler process/context binding
AND every additional enabled profile stream is complete under its own contract
```

A duplicate shard, missing shard, stream mismatch, cross-stream append,
uncommitted path, invalid summary/digest, or missing pair fails joint evidence
closed without deleting a valid diagnostic artifact.

## 7. Compatibility proof obligations

PR-I1 tests must prove, with scheduler disabled and enabled:

1. lifecycle golden bytes, path, capacity, and close behavior are unchanged;
2. KV-recovery golden bytes, path, capacity, and close behavior are unchanged;
3. all enabled streams share one process UUID but have independent sequences,
   queues, ledgers, summaries, digests, descriptors, and receipts;
4. scheduler failure cannot consume another stream's reserve or mutate serving;
5. duplicate/cross-stream paths and manifests fail closed;
6. fork/restart creates a new process identity and never reuses inherited
   stream writer state.

The PR-C1 verifier checks contract bytes and fixtures only. It is not the PR-I1
exporter compatibility proof.

## 8. Approval effect

Approval must cite this overlay, the scheduler wire contract, configuration,
run-identity vectors, and approval-candidate digests. It authorizes only
default-off implementation work in later PRs. It does not authorize runtime
activation, NPU collection, mechanism evidence, performance claims, merge, or
M0.
