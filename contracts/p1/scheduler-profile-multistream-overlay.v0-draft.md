# Scheduler Profile Shard Scope — Route B Architecture Review Candidate

- Status: `architecture_review_candidate`
- Evidence status: `NOT_SCIENTIFIC_EVIDENCE`
- Route: `B — launcher-injected identity, experiment-owned composition`

This overlay changes only scheduler-stream shard ownership and scope. It does
not edit the owner-frozen `rlp.trace/v1alpha1` bytes and does not supersede the
separately approved KV-recovery stream.

## 1. Stream roster

The closed profile-stream roster is:

- `lifecycle`: existing base lifecycle stream;
- `kv_recovery`: separately versioned KV-recovery stream when its independent
  gates admit it; and
- `scheduler`: the aggregate scheduler stream defined by this candidate.

Each stream has an independent writer, sequence, limits, loss ledger, summary,
and committed-shard receipt. One stream's spare capacity cannot be borrowed by
another.

## 2. Scheduler shard identity

Before launching a server, the experiment repository constructs the expected
process roster and injects this complete scheduler scope:

```text
experiment_run_id
server_instance_id
process_instance_id
scheduler_shard_id
process_role
profile_stream = scheduler
```

The values are opaque bounded identifiers. The plugin records them; it does
not derive them from PID, rank, device, context, hostname, path, or time.

`scheduler_start` and `scheduler_summary` repeat the complete scope. Data and
loss records carry `scheduler_shard_id` and inherit the other values only
after the reader validates the unique start record. A mismatch between either
endpoint, the manifest, or any data record is a whole-shard failure.

`process_instance_id` names the process that produced the scheduler facts. It
does not assert that the same process owns a device profile. No field in this
overlay selects a raw profile, `analysis.db`, rank, or device.

## 3. Local ID namespace

The scheduler shard owns independent counters beginning at zero for cycle,
batch, execution-step, data-record, and loss-interval identities. Canonical
IDs are scoped by `scheduler_shard_id`:

```text
<scheduler_shard_id>:cycle:<cycle_seq>
<scheduler_shard_id>:batch:<batch_seq>
<scheduler_shard_id>:step:<execution_step_seq>
<scheduler_shard_id>:loss:<loss_interval_seq>
```

These IDs are scheduler-local evidence. They are never reused as TraceLoom
runtime-call IDs, device-work IDs, global execution IDs, or cross-run keys.

## 4. Physical ownership and disabled behavior

One `scheduler_shard_id` owns one mode-`0600`, append-only scheduler shard and
one writer. The v1 path template is:

```text
<base>.rlp-scheduler.<scheduler_shard_id>.jsonl
```

The launcher must ensure that the bounded shard ID is filesystem-safe. The
writer still uses exclusive creation and publishes only an immutable
successful close receipt.

When the scheduler stream is disabled, it allocates no IDs, opens no file, and
changes no scheduler behavior. The manifest records the stream as inactive;
an absent shard is not silently treated as a complete empty shard.

## 5. Completeness and paired admission

The frozen P0 zero-loss rule is preserved for every stream. A scheduler shard
is complete only when it has:

- exactly one valid first `scheduler_start` and one valid final
  `scheduler_summary`;
- endpoint identity equal to the manifest scope;
- a drained close with balanced counts and matching content digest;
- complete record-sequence coverage; and
- zero loss intervals, dropped records, control loss, and writer failures for
  formal admission.

Diagnostic fixtures may contain an accounted loss interval to exercise the
ledger, but they are not formal complete evidence.

The experiment repository builds its expected shard roster before collection.
It admits only explicit committed paths and exact SHA-256 values. A glob may
report an unexpected file but cannot add that file to the run.

## 6. Cross-source composition boundary

The experiment run manifest separately maps:

```text
scheduler_shard_id -> process_instance_id -> experiment_run_id
profile_source_id -> process_instance_id, rank, device_id
analysis.db -> profile_source_id -> raw profile and TraceLoom commit
```

Only the experiment composer may combine those mappings. TraceLoom and the
scheduler shard do not infer or certify them. PID/context is allowed only as
local diagnostic metadata and time proximity is allowed only as correlation
after explicit mapping and clock validation.

## 7. Compatibility

Existing lifecycle and KV-recovery shards retain their approved identities,
record schemas, writers, and receipts. Implementations may share bounded
writer machinery, but must not share mutable sequence, queue, close, or loss
state across streams.

This overlay replaces the earlier proposal's cross-database use of
`process_uuid`, analyzer-derived run identity, and PID/context binding. Those
concepts are not aliases for the Route B launcher identifiers.

## 8. Approval effect

Approval of this architecture authorizes drafting a content-addressed
scheduler wire candidate. It does not authorize runtime hooks, activation,
profile collection, experiment composition, scientific evidence, or merge.
