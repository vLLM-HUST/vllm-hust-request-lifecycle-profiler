# Scheduler Profile Wire Contract — Route B Draft

- Status: `draft`
- Evidence status: `NOT_SCIENTIFIC_EVIDENCE`
- Schema: `rlp.scheduler/v1alpha1`
- Encoding: deterministic UTF-8 JSONL

This contract records scheduler-local facts. It does not establish a global
TraceLoom run, choose a profile database, bind a runtime PID/context to a
rank, or create a scheduler-to-device exact relation. Those responsibilities
belong to the experiment run manifest and composer.

## 1. Supported profile

The first profile is one host, synchronous scheduling, one in-flight
execution step, uniprocess execution, decoder-only generation, `n=1`, no
speculative decoding, and no KV/EC transfer connector. The exact runtime
profile is defined in `scheduler-profile-config.v1alpha1.json`.

Unsupported modes preserve serving behavior and fail formal scheduler evidence
closed. They do not emit a plausible partially supported shard.

## 2. Encoding and primitive domains

Records use sorted keys, compact separators, no NaN/Infinity, and one trailing
LF byte. The encoded record including LF is at most the configured maximum.
Unknown members are forbidden.

- uint32 and uint64 reject booleans, negative values, and overflow;
- Git commits are 40 lowercase hexadecimal characters;
- SHA-256 values are 64 lowercase hexadecimal characters;
- `clock_domain_id` is 32 lowercase hexadecimal characters;
- launcher identifiers are printable ASCII strings within their stated
  bounds; and
- `scheduler_shard_id` matches `[A-Za-z0-9._-]{1,64}`.

Every record contains `schema_version`, `record_type`, and
`scheduler_shard_id`. Every data record additionally contains `record_seq`.
The start and summary contain the complete launcher-injected scope:

```text
experiment_run_id
server_instance_id
process_instance_id
scheduler_shard_id
process_role
profile_stream
```

Interior records inherit the remaining scope only after the shard endpoints
and manifest binding validate.

## 3. Local identity and relations

Cycle, batch, step, and loss counters are uint64 sequences local to one
scheduler shard. Canonical IDs are:

```text
<scheduler_shard_id>:cycle:<cycle_seq>
<scheduler_shard_id>:batch:<batch_seq>
<scheduler_shard_id>:step:<execution_step_seq>
<scheduler_shard_id>:loss:<loss_interval_seq>
```

The v1 relation is bijective:

```text
schedule_cycle 1 -> 1 logical_batch 1 -> 1 execution_step
```

This relation includes zero-token control batches. A local step ID is not a
cross-database or provider submission identity.

## 4. Closed record roster

The only record types are:

```text
scheduler_start
schedule_cycle
logical_batch
execution_step_start
execution_step_end
clock_bridge_sample
loss_interval
scheduler_summary
```

### 4.1 `scheduler_start`

Exactly one first record with:

- the complete launcher-injected scope;
- `started_monotonic_ns`, `clock_source=CLOCK_MONOTONIC`, and
  `clock_domain_id`;
- runtime, device-plugin, and parent-protocol commits;
- `runtime_profile_id`; and
- the complete configured `limits` object.

It contains no profiler PID/context, analyzer run ID, profile-source ID,
rank/device identity, raw-profile path, or analysis database path.

### 4.2 `schedule_cycle`

One record contains:

- `record_seq`, `cycle_seq`, `schedule_cycle_id`, and `logical_batch_id`;
- scheduler-call start/end monotonic timestamps and `completed|failed`;
- waiting/running request counts before and after;
- configured/effective token and active-sequence limits; and
- the fixed-cardinality token-budget and active-sequence-cap summaries.

The end timestamp is not earlier than the start timestamp.

### 4.3 `logical_batch`

One record links its cycle and step and contains scheduled request/token
counts, prefill/decode token counts, and:

```text
runtime_device_relation_candidate_eligible
```

For `work`, scheduled tokens and scheduled requests are positive, token counts
balance, and candidate eligibility is true. For `empty_control`, every count
is zero and candidate eligibility is false. Eligibility authorizes only a
later composer attempt; it is not a device-attribution claim.

### 4.4 `execution_step_start`

One record contains its local step/batch IDs, `dispatch_monotonic_ns`, and
`dispatch_kind=uniproc_execute_model`. It carries no target PID, context,
rank, device, or profile database.

### 4.5 `execution_step_end`

One record contains the same step/batch identity,
`final_result_monotonic_ns`, `execution_outcome`, and `sampling_status`.
Dispatch is no earlier than the linked cycle end and final result is no earlier
than dispatch.

### 4.6 `clock_bridge_sample`

One sample contains `sample_sequence`, `clock_domain_id`,
`monotonic_before_ns`, `realtime_ns`, and `monotonic_after_ns`. The bracket is
ordered and the domain equals the start record. A sample is scheduler-local
clock metadata, not a global calibration decision.

### 4.7 `loss_interval`

A maximal interval contains its local loss ID, closed reason, inclusive data
sequence range, total dropped count, per-record-type counts, and first/last
observation timestamps. Per-type counts and sequence width exactly balance.

### 4.8 `scheduler_summary`

Exactly one final record repeats the complete launcher scope and contains end
time, attempted/written/dropped counts, data sequence range, writer/close
status, and `content_sha256`. The digest covers exact LF-terminated bytes from
the start through the last non-summary record.

## 5. Constraint summaries

The token-budget summary has the Cartesian bucket roster:

```text
queue = running | waiting | skipped_waiting
mode  = not_limited | clipped | stopped_no_chunk
```

The active-sequence-cap summary has:

```text
queue = running | waiting | skipped_waiting
mode  = not_limited | stopped_at_cap
```

Buckets appear in the configured lexical roster order. Counts, first witness,
unclassified witness, and evaluated/accounted/unclassified totals balance
exactly. No per-request unbounded list is emitted.

## 6. Loss and formal completeness

An attempted data record consumes `record_seq` before validation,
serialization, or enqueue. Written sequences plus loss ranges cover exactly
`[0, attempted_data_count)`, without overlap or gaps.

The ledger can describe loss, but formal completeness preserves the zero-loss
rule: a shard with any loss interval, data/control drop, writer failure,
timeout, invalid digest, or unexplained sequence gap is ineligible. A valid
diagnostic summary is not automatically formal evidence.

## 7. Clock and experiment-composer boundary

The producer records scheduler-local monotonic facts and bridge samples. It
does not compose clocks with TraceLoom. The experiment composer may create:

- `exact` only from one explicit stable producer execution identity carried
  by both sides;
- `correlated` from explicit manifest mapping, a compatible clock or accepted
  calibration, and one unique legal containment;
- `ambiguous` while retaining every legal candidate;
- `unmatched` when supported inputs have no candidate; or
- `unsupported` when mapping, calibration, local relation, or schema support
  is absent.

Timestamp proximity never yields `exact`, and the scheduler shard never
selects the corresponding `analysis.db`.

## 8. Boundedness and writer behavior

All configured queue, byte, batch, cadence, close, duration, and artifact
limits are wire values. The producer performs bounded in-memory work and
non-waiting enqueue only. One writer owns file operations. Failures are
serving-fail-open and evidence-fail-closed.

The capacity proof uses the configured maximum cycle rate, maximum records per
cycle, writer service gap, clock samples, reserved control capacity, formal
duration, maximum record bytes, and disk margin. The standalone verifier
recomputes every equation and generates a maximal legal cycle record.

## 9. Manifest and shard semantics

The physical shard is one mode-`0600` append-only file per
`scheduler_shard_id`. Only a drained, summary-written immutable close receipt
may enter the experiment manifest. A raw path or matching glob is not an
admission receipt.

The experiment manifest verifies endpoint scope, path, and SHA-256. It owns
all process/rank/device and profile-source mappings. Unknown databases are not
admitted, and missing rank values are not inferred.

## 10. Claim boundary

This contract supports scheduler-local facts and, after separate experiment
composition, observed associations with profiler-visible runtime/device work.
It does not support device-idle cause, idle causal attribution, exact stall
cause, or a provider exact-submission edge without an explicit shared producer
identity.

## 11. Validation and lifecycle

Ordinary review and CI validate:

1. schema, record roster, primitive domains, and all fields;
2. launcher-injected run/process/shard scope;
3. scheduler-local ID grammar and cycle/batch/step relations;
4. zero-token, constraint, clock, loss, and summary semantics;
5. bounded writer limits and disabled/fail-open behavior;
6. Route B experiment-owned cross-source composition;
7. exact/correlated/ambiguous/unmatched/unsupported status meanings; and
8. the restricted claim boundary and remaining implementation gates.

Passing these checks does not activate runtime hooks, admit formal collection,
or turn the contract into scientific evidence or a mechanism claim.
