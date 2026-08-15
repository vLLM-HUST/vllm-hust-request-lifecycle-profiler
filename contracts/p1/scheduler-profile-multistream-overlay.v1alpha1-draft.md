# Scheduler Shard Scope — Route B Draft

- Status: `draft`
- Evidence status: `NOT_SCIENTIFIC_EVIDENCE`
- Scheduler wire: `rlp.scheduler/v1alpha1`

This overlay specializes the Route B architecture without changing the
separately versioned lifecycle or KV-recovery streams.

## 1. Closed stream roster

`profile_stream` is `lifecycle`, `kv_recovery`, or `scheduler`. This contract
defines only the last value. Each active stream has an independent
writer, queue, sequence, loss ledger, summary, close result, and committed
shard receipt.

## 2. Launcher-injected scope

The experiment launcher supplies the scheduler plugin with exactly these
opaque, printable ASCII identifiers before any scheduler record can be
emitted:

```text
experiment_run_id     1..128 bytes
server_instance_id    1..128 bytes
process_instance_id   1..128 bytes
scheduler_shard_id    1..64 bytes, filesystem-safe `[A-Za-z0-9._-]+`
process_role           `engine_core` in the v1 runtime profile
profile_stream         `scheduler`
```

The full scope is required in `scheduler_start` and `scheduler_summary`.
Every data/loss record carries the exact `scheduler_shard_id`. The complete
scope of those interior records is inherited from the unique validated start
record.

The shard does not carry a raw-profile path, analysis database path,
`profile_source_id`, rank, device, profiler PID/context, analyzer run ID, or a
claim that any database matches the shard.

## 3. Writer ownership

One scheduler shard is written to:

```text
<base>.rlp-scheduler.<scheduler_shard_id>.jsonl
```

with mode `0600`, exclusive creation, one persistent writer owner, and an
independent data-record sequence. Rotation is outside v1. The launcher rejects
a shard ID that is unsafe for the path template.

## 4. Local identifiers

Cycle, batch, step, and loss counters start at zero and are never reused in a
shard. Their canonical values are:

```text
<scheduler_shard_id>:cycle:<cycle_seq>
<scheduler_shard_id>:batch:<batch_seq>
<scheduler_shard_id>:step:<execution_step_seq>
<scheduler_shard_id>:loss:<loss_interval_seq>
```

They have no cross-database meaning.

## 5. Disabled behavior

With scheduler profiling disabled, the plugin opens no scheduler shard,
allocates no scheduler ID, invokes no clock bridge, and does not alter
scheduling, execution, or outputs. The experiment manifest records the stream
as inactive. Absence is not converted into a complete empty shard.

## 6. Receipt and completeness

The run manifest uses only the immutable committed path returned by a drained,
summary-written close. It never discovers the expected roster with a glob.

A scheduler shard is formally complete only if all wire checks pass and the
whole shard has zero data loss, zero control loss, zero loss intervals, zero
writer failures, and `close_outcome=drained`. The golden loss fixture is a
diagnostic ledger test and therefore intentionally not formal evidence.

## 7. Experiment composition

The experiment repository separately and explicitly maps the scheduler shard
and every profile source. The scheduler shard cannot decide which
`analysis.db` belongs to it. Cross-source identity cannot be inferred from
PID/context, rank/device equality, filenames, database enumeration, or time
proximity.

## 8. Validation effect

Ordinary review and CI validate this overlay together with the wire contract,
configuration, fixture, verifier, and tests. Passing those checks does not
activate the experiment composer or runtime collection and does not establish
scientific evidence.
