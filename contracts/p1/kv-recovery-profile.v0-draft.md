# Optional KV-Recovery Profile v0 Draft

> **Historical, non-normative design note.** Approval, freeze, authority,
> attestation, digest-chain, and activation-gate language below is retained only
> to explain project history. Current policy is defined by `AGENTS.md`,
> `CONTRIBUTING.md`, `.github/BRANCH_POLICY.md`, the implementation, and tests.

- Proposed profile ID: `rlp.kv-recovery/v1alpha1`
- Review status: `owner_review_required`
- Evidence status: `NOT_M0_PROVEN`
- Communication status: `BLOCKED_PENDING_SEPARATE_ISSUE2_MAPPING_ARTIFACT`
- Runtime implementation status: `NOT_STARTED`

This document is a content-addressing candidate, not an approved contract. It
does not alter the owner-frozen `rlp.trace/v1alpha1` bytes, authorize runtime or
device-plugin edits, enable a non-`none` communication mode, admit an NPU run,
or establish a performance result.

## 1. Purpose

The profile defines the optional evidence needed to reconstruct one real
pressure-driven KV recovery episode:

```text
preempt
  -> restore_start
  -> restore_done
  -> scheduler_wakeup
  -> zero or more reasoned requeue observations
  -> admission
  -> first_prefill_or_decode
```

It supplies the versioned runtime meaning that the typed offline model in
`src/vllm_request_lifecycle_profiler/kv_recovery.py` intentionally does not
freeze. Its output may be adapted to `KVRecoveryEvent` only after the complete
profile episode passes every identity, ordering, loss, process-roster, and
communication check below.

The profile answers three separate timing questions:

1. how long the accepted H2D restore took at the worker observation boundary;
2. how long completion took to become visible to the scheduler and reach a
   schedulable state; and
3. how long admission and first resumed compute took after that wakeup.

It must not relabel ordinary queueing, an invalid-load recompute, a prefix hit,
or a device-event duration as a complete pressure-recovery episode.

## 2. Exact dependencies

| Dependency | Frozen or audited identity | Status in this candidate |
| --- | --- | --- |
| Base runtime contract | `contracts/p0/runtime/minimum-runtime-contract.v0-draft.md`, SHA-256 `122963930919073179d4844422d21e85da3a522def3ace723eb992eac43cdade` | owner-frozen input; immutable |
| Base phase taxonomy | `contracts/p0/runtime/phase-taxonomy.v0-draft.md`, SHA-256 `82aae94c5d124b846f77684e239714d51791115608e786079c4ea4bd4ca05abd` | owner-frozen input; immutable |
| Offline KV model | `src/vllm_request_lifecycle_profiler/kv_recovery.py`, SHA-256 `9b533e1620d4e282ed33eadcf8f27bb63a71cab5bfe0a6140823d9bb3d6b9849` | typed offline target, not a wire contract |
| Runtime core | `vLLM-HUST/vllm-hust@f229ba7cad21a4dba58681af6738a9fd947388e2` | audited source anchor |
| Device plugin | `vLLM-HUST/vllm-ascend-hust@cafad89a5e103f31ea517c1edb56130578c3cd56` | audited source anchor; selected legacy paths are incompatible |
| Benchmark snapshot | `vLLM-HUST/vllm-hust-benchmark@0858cdb326e88ebaf8027966ba754da5ea800db4` | contains no frozen issue-#134 executable configuration |
| Idle/communication semantics | profiler `main@7e10622eb5755e1af544546e93e3f63a91214ffc`, `docs/idle_evidence_contract.md` Draft v4.3, SHA-256 `8edb42b706b6cab14dfde2b109841cb8af090883c9ea86696ee779de21d0c9ed` | normative design input, not an approved runtime subtype profile |

Draft v4.3 contributes interval algebra, communication canonicalization,
clock-alignment rules, conservative idle vocabulary, evidence levels, and
forbidden claims. It does not supply request/recovery identity, a runtime
D2H/H2D emitter roster, or a frozen `issue2:<version>:<subtype>` mapping. This
profile freezes only recovery-side observations and the requirements that a
future communication mapping must satisfy. Section 9 contains an H2D mapping
fragment for review, not a complete or activatable issue-2 contract.

## 3. Supported scope

The first profile version is deliberately narrow:

- one host and one `CLOCK_MONOTONIC` clock domain;
- TP=1, PP=1, one device rank (`rank=0`, `world_size=1`);
- decoder-only text generation, `sampling_n=1`, `sample_index=0`;
- one pressure-preemption episode per accepted decomposition, with exactly one
  request/lifecycle/epoch identity and one successful H2D restore; a process
  shard may contain other request-scoped transfer facts and run-scoped wait
  sets, but they never join the episode by timestamp or queue order;
- the runtime-core `OffloadingConnector` family with an explicitly frozen
  spec and resolved configuration;
- exactly one successful H2D restore transfer for the episode;
- no restore retry, partial restore, transfer failure, rank failure, or
  cross-host correlation; and
- tracing through the already bounded runtime hook/exporter architecture,
  with no log parsing and no producer-path file or logging-handler I/O.

The following are diagnostic-only and cannot produce a valid profile episode:

- a synchronous or asynchronous invalid-KV-load recovery that did not first
  perform the pressure-driven `RUNNING -> PREEMPTED` transition;
- a normal external prefix-cache load for a new request;
- a device-plugin `RecomputeCPUOffloadConnector` episode;
- device-plugin `NPUOffloadingSpec` or `NPUTieringOffloadingSpec` under the
  audited fixed pair;
- more than one rank, more than one successful restore job for the episode,
  or any retry/failure/cancellation;
- an episode whose request, lifecycle, recovery epoch, transfer, block set,
  process receipt, or communication dependency cannot be joined exactly.

These restrictions are profile-version limits, not claims that the underlying
runtime lacks the excluded behavior.

## 4. Relationship to the base trace

`rlp.kv-recovery/v1alpha1` is an optional profile stream. It does not add a
record type, event name, array, float, or sequence field to
`rlp.trace/v1alpha1`, and it does not make historical no-pressure traces look
incomplete. A complete profile episode references, but never replaces, the
base trace.

| Profile observation | Required base-DAG association |
| --- | --- |
| `preempt` | exact engine `preempted` event that closes base epoch `e`; the profile recovery episode is the next epoch `e+1` |
| `restore_start` | proposed communication-span start for `h2d_restore`; no association is legal while the specialty communication mapping is unapproved |
| `restore_done` | matching communication-span end for the same transfer and block set |
| `scheduler_wakeup` | profile-only scheduler observation; it must link explicitly to `restore_done` and the later profile `admission`, which carries both base admission boundary IDs |
| `requeue` | profile-only reasoned defer after wakeup; the base epoch's one `requeued` event remains the preemption-to-waiting transition and is not duplicated per scheduler pass |
| `admission` | exact base `resumed` event after the request reaches `RUNNING` |
| `first_prefill_or_decode` | versioned worker child observation inside the active base prefill/decode span after `resumed`; it references, but never redefines, the engine-core-owned base `prefill_started` or `decode_started` event |

The profile must carry the referenced base event IDs. Timestamp adjacency,
matching text, request-log order, or a shared process is not a substitute for
those links.

## 5. Identity model

### 5.1 Request and sequence

- `trace_id` remains the canonical 32-lowercase-hex root join key.
- `engine_lifecycle_id` is exactly `trace_id:e:0`.
- The offline `sequence_id` is exactly that engine lifecycle ID. P1 must not
  invent a runtime sequence identifier that the audited runtime does not own.
- `runtime_request_id` is the complete internal `Request.request_id`, copied
  without truncation or reconstruction. It must be printable ASCII, nonempty,
  and at most 128 bytes. A longer or nonprintable value makes the episode
  diagnostic-only.
- `request_id_kind` is exactly `engine_internal` in this version. The frontend
  stores the external request ID separately but constructs the internal value
  as that external value plus a random suffix. The separate external field is
  not available on scheduler `Request` at the audited runtime commit and may
  not be recovered by parsing the internal value. A later explicit external-ID
  field requires a new profile version.
- Every participating process receives the same explicit mapping from
  `runtime_request_id` to `trace_id` and `engine_lifecycle_id`; no process may
  regenerate it.

`runtime_request_id` is a bounded, noncanonical, privacy-sensitive diagnostic
field; `trace_id` and `engine_lifecycle_id` remain the canonical joins. A
controlled run must supply opaque ASCII request IDs generated for the
experiment and containing no prompt, account, endpoint, or human identifier.
Formal admission requires a recorded privacy review of that generator. The
adapter never exports the separate external-ID field, raw prompt/tokens, block
hashes, cache salt, trace headers, or free-form exception text. Profile shards
use exporter-owned mode-0600 files and the same bounded retention policy as
the base trace.

### 5.2 Recovery episode

- Epoch zero is the initial engine epoch and is not a recovery episode.
- Immediately before a committed preemption, the candidate recovery epoch is
  `request.num_preemptions + 1`.
- The `preempt` record is emitted only after the scheduler has committed the
  status transition and increment. Its `recovery_epoch` must equal the
  resulting `request.num_preemptions` and must be positive.
- The referenced base `preempted` event belongs to the closing epoch
  `recovery_epoch - 1`; the later base `requeued`, `admission_started`, and
  `resumed` events belong to `recovery_epoch`. Any other relation is invalid.
- `episode_id` is ASCII
  `engine_lifecycle_id:k:recovery_epoch`, with canonical unsigned decimal
  epoch encoding and no leading zero.
- An episode ID is never reused, even when capture fails.

An invalid-load recompute does not increment `num_preemptions` and therefore
cannot acquire a pressure-recovery episode ID.

### 5.3 Transfer

- `transfer_id` is ASCII `process_uuid:t:transfer_seq`, where `transfer_seq`
  is a per-worker uint64 counter allocated before submission and never reused.
- The runtime connector's numeric `job_id` is preserved as `connector_job_id`
  but is only unique inside one connector-scheduler instance. It is never the
  canonical transfer identity.
- A transfer is scoped by profile digest, run ID, process UUID, rank,
  direction, connector/spec identity, and transfer ID.
- `direction` is `d2h` or `h2d`; `operation` is `d2h_preserve` or
  `h2d_restore`. For the seven-stage episode, `restore_start` and
  `restore_done` must reference the same successful `h2d_restore` transfer.
- `src_medium`/`dst_medium` are exactly `device_hbm`/`host_cpu` for D2H and
  `host_cpu`/`device_hbm` for H2D.

### 5.4 Logical blocks

Physical device and CPU block numbers are allocator-, process-, rank-, tier-,
direction-, and time-local; they can be reused immediately after release.
They are not canonical block identity and are forbidden as the sole join key.

The engine-core adapter assigns an opaque 32-lowercase-hex `logical_block_id`
to each selected `(engine lifecycle, KV group, logical block ordinal)` when it
is first selected for offload or snapshotted for preemption, before physical
blocks are freed. The same run-local IDs are propagated through connector
metadata to later restore submission and completion. Raw token IDs, prompt
text, block hashes, or offload keys are not exported.

A `block_set_id` is the lowercase SHA-256 of the canonical UTF-8 sequence:

```text
profile_id NUL run_id NUL engine_lifecycle_id NUL
group_index ":" logical_ordinal ":" logical_block_id LF
...
```

Rows are sorted by `(group_index, logical_ordinal)`. Integers use canonical
unsigned decimal. The set is nonempty, has at most 4096 rows, has no duplicate
coordinate or logical ID, and is identical at restore start and completion.
Profile records may chunk those rows in groups of at most 64, but chunking
does not change `block_set_id`.

Physical source/destination block IDs may appear only in a diagnostic block
binding with the full scope above. Formal episode matching uses the logical
set and rejects any missing, changed, duplicated, or unbounded binding.

## 6. Profile record grammar

The implementation must reuse the bounded queue, loss accounting, close
deadline, process receipts, and writer ownership of `RuntimeLifecycleHooks`.
It may parameterize that implementation for one profile shard per
participating process; it must not create an independent exporter, perform
direct file I/O at a call site, or mix profile records into a base
`rlp.trace/v1alpha1` shard.

The profile path is exactly
`<base>.rlp-kv-recovery.<process_uuid>.jsonl`, created exclusively with mode
0600 by the same writer owner. `<base>` is the configured export base, not a
file. The profile and base shard reuse the same process UUID and are admitted
as an explicit pair in the independently frozen expected-process roster; a
convenience glob cannot discover either expected set.

Every profile record contains these common envelope fields, plus exactly the
fields required by its record type:

- `schema` = `rlp.kv-recovery/v1alpha1`;
- `record_type` from the closed roster below; and
- the emitting base-trace `process_uuid`.

The closed record roster is `profile_start`, `block_set_chunk`,
`wait_set_chunk`, `transfer_event`, `recovery_event`, `loss_interval`, and
`profile_summary`. All strings are printable ASCII unless a field is
explicitly hexadecimal. All integers are unsigned and use the P0
uint32/uint64 domains. Floats, negative values, unbounded objects, and unknown
fields are forbidden. An encoded record including LF is at most 4096 bytes.

### 6.1 `profile_start`

Exactly one first record per profile shard. It contains:

- `pid`, `started_timestamp_ns`, `clock_source=CLOCK_MONOTONIC`, and
  `clock_domain_id` under the frozen P0 construction;
- `profile_id`, the approved `profile_sha256`, and a run-level 32-hex `run_id`;
- exact 40-hex profiler parent, runtime core, and device plugin commits;
- the base trace schema and both frozen P0 digests;
- `rank=0`, `world_size=1`;
- `implementation_family=runtime_core_offloading_connector`;
- `connector_name=OffloadingConnector` and the exact frozen `spec_name`;
- `communication_mode=issue2:kv-recovery-v1alpha1` plus the
  `communication_mapping_sha256`; that digest is null only in diagnostic
  output, while formal admission requires the 64-lowercase-hex digest of a
  separately approved mapping artifact; and
- `limits` containing the exact keys below and no others.

| Wire key | Type | Value |
| --- | --- | ---: |
| `data_capacity_records` | uint32 | 4096 |
| `reserved_capacity_records` | uint32 | 64 |
| `max_record_bytes` | uint32 | 4096 |
| `max_queued_bytes` | uint64 | 17039360 |
| `max_batch_records` | uint32 | 128 |
| `max_batch_bytes` | uint32 | 262144 |
| `write_interval_ms` | uint32 | 100 |
| `close_timeout_ms` | uint32 | 2000 |
| `max_metadata_bytes` | uint32 | 1024 |
| `max_logical_blocks_per_block_set` | uint32 | 4096 |
| `max_block_rows_per_chunk` | uint32 | 64 |
| `max_transfer_records_per_lifecycle` | uint32 | 4096 |
| `max_transfer_ids_per_wait_set` | uint32 | 4096 |
| `max_wait_set_rows_per_chunk` | uint32 | 64 |
| `max_wait_sets_per_process_shard` | uint32 | 64 |
| `max_requeue_observations_per_episode` | uint32 | 64 |
| `max_runtime_request_id_bytes` | uint32 | 128 |
| `shard_ownership` | ASCII string | `one_process_one_append_only_profile_shard` |

### 6.2 Data-record common fields

Each `block_set_chunk`, `wait_set_chunk`, `transfer_event`, and
`recovery_event` is a data record with these process/run fields:

- `record_seq`, allocated atomically in producer-observation order before
  validation or enqueue;
- `record_id` = `process_uuid:k:record_seq`;
- `run_id`;
- `timestamp_ns` and `clock_domain_id`; and
- `profile_id` and `profile_sha256`.

`block_set_chunk`, `transfer_event`, and `recovery_event` are request-scoped
and additionally contain exactly `trace_id`, `engine_lifecycle_id`,
`runtime_request_id`, `request_id_kind`, `sample_index=0`, `recovery_epoch`,
and `episode_id`. A `wait_set_chunk` is process/run-scoped and must not contain
those request fields: its exact member transfer records carry their own
request/lifecycle/epoch identities.

Failed construction consumes `record_seq` and opens the same deterministic
loss accounting used by P0. `record_seq` is audit order only.

`recovery_epoch` and `episode_id` are nonnull for every H2D-restore block set,
H2D-restore transfer, and recovery milestone. A proactive `d2h_preserve`
transfer and its block-set chunks may precede any pressure episode; only for
those records they are null. Such a D2H record remains attributable to the
exact request/lifecycle, transfer, and logical block set, but it is not
retroactively assigned to a future episode by timestamp matching. The
seven-stage decomposition requires the H2D restore and does not require a
preceding D2H transfer.

The request-scoped `recovery_epoch` and `episode_id` rules do not apply to a
`wait_set_chunk`. A wait set can contain transfers from more than one request
or episode because the audited worker flushes a process-local set. An episode
associates with a wait set only by exact membership of its `transfer_id`; it
never inherits an identity from the wait record itself.

### 6.3 `block_set_chunk`

The record adds `block_set_id`, `chunk_index`, `chunk_count`,
`total_block_count`, and a nonempty `blocks` array. Each block entry contains
exactly `group_index`, `logical_ordinal`, and `logical_block_id`. Chunks are
contiguous from zero, have one declared count and total, and reconstruct the
canonical rows in section 5.4 exactly once.

### 6.4 `wait_set_chunk`

For a nonempty `OffloadingWorker.wait(job_ids)` call, resolve every connector
job ID to its profile `transfer_id`, sort the unique transfer IDs
lexicographically, and reject any missing, duplicate, already-failed, foreign-
process, foreign-run, or over-bound member. `wait_set_id` is SHA-256 over the
canonical UTF-8 sequence:

```text
profile_id NUL run_id NUL process_uuid NUL
transfer_id LF
...
```

One or more contiguous `wait_set_chunk` records add
`operation=transfer_wait`, `wait_set_id`,
`chunk_index`, `chunk_count`, `total_transfer_count`, and a nonempty
`transfer_ids` array of at most 64 members. The set has at most 4096 members.
Chunks reconstruct the exact sorted list once; the declared total, digest, and
every referenced `transfer_event` must verify. Hash and count alone are not
sufficient evidence. The reconstructed set may contain multiple request,
lifecycle, or episode identities; association remains member-by-member through
the referenced transfer records. A call with an unresolved or foreign member
cannot be represented partially: it consumes the attempted record sequence,
enters loss accounting as `serialization_failure`, and invalidates every
episode whose transfer membership could be affected.

### 6.5 `transfer_event`

The record adds:

- `transfer_id`, `connector_job_id`, `rank=0`, `world_size=1`;
- `operation`, `direction`, `src_medium`, `dst_medium`, and `block_set_id`;
- `transfer_phase=submit|done`;
- `bytes_moved`, null at submit and a positive uint64 at successful done;
- `device_duration_ns`, null unless a real device event reports a positive
  duration at done;
- `success`, null at submit and exactly `true` at a valid done; and
- `failure_code`, null for a valid episode.

Submit means the worker accepted `submit_load` or `submit_store`, not that the
scheduler merely constructed metadata. Done means the worker observed the
matching successful `TransferResult`. A queueing estimate or scheduler-side
metadata creation cannot substitute for either boundary.

The host duration is `done.timestamp_ns - submit.timestamp_ns`. A device
duration is supplemental mechanism evidence under Idle Evidence Contract v4.3
and cannot reorder host lifecycle events without an approved clock model.
The audited `TransferResult.transfer_time` exposes finite positive elapsed
seconds as a float (the Ascend worker has already converted device-event
milliseconds by multiplying by `1e-3`). The wire integer is therefore
`floor(transfer_time_seconds * 1_000_000_000 + 0.5)`; a nonfinite, nonpositive,
or overflowing value is unavailable rather than guessed.

A diagnostic failed completion sets `success=false` and uses one closed
`failure_code`: `submit_rejected`, `transfer_failed`, `cancelled`, `timeout`,
`size_unavailable`, or `unclassified`. It invalidates the episode. The current
audited connector asserts successful submission/completion, so supporting a
real failure record requires a separately reviewed runtime change; absence of
that change never turns failure into success.

### 6.6 `recovery_event`

The record adds these fields, present with null when inapplicable:

- `stage`, one of the seven stages;
- `occurrence`, zero for unique stages and contiguous zero-based order for
  `requeue`;
- `base_event_id` and `base_admission_started_event_id`;
- `from_profile_event_id` for the explicit predecessor;
- `transfer_id`, `block_set_id`, and `bytes_moved`;
- `requeue_reason`;
- `compute_kind=prefill|decode`;
- `child_observation_kind=worker_model_forward_entry`; and
- `base_association_kind=phase_child_observation` and
  `base_association_evidence=instrumented_execution_context`; and
- `request_status_before` and `request_status_after`.

Unique stages occur exactly once. `requeue` occurs zero to 64 times. The H2D
transfer's submit and done timestamps, identity, block set, and bytes must
equal the corresponding restore milestone fields; the adapter must not create
independent copies with merely similar values.

`base_event_id` is required for `preempt`, both restore milestones,
`admission`, and `first_prefill_or_decode`, and is null for scheduler wakeup and
requeue observations. For `admission`, it identifies base `resumed` and
`base_admission_started_event_id` identifies the matching earlier
`admission_started`; that second field is null for every other stage. For
`first_prefill_or_decode`, `base_event_id` identifies the already active
engine-core-owned base phase start, while `child_observation_kind` identifies
the separate worker child boundary. `child_observation_kind` is null for every
other stage. The two base-association fields are required only for that worker
child and null otherwise. They define a profile association, not a new frozen
P0 edge or event. The worker timestamp never changes the base event timestamp,
component, owner, or span boundary.

### 6.7 Loss and summary

A `loss_interval` has `loss_interval_seq`, `loss_interval_id`, `reason`,
`first_dropped_record_seq`, `last_dropped_record_seq`, `dropped_count`,
`block_set_chunk_count`, `wait_set_chunk_count`, `transfer_event_count`,
`recovery_event_count`, `first_observed_timestamp_ns`, and
`last_observed_timestamp_ns`, plus the common envelope/profile digest. The
reason is `serialization_failure`, `queue_overflow`, `writer_failure`, or
`close_timeout`. All counts/timestamps/sequences are uint64, the interval IDs
use `process_uuid:l:loss_interval_seq`, and:

```text
dropped_count
  == last_dropped_record_seq - first_dropped_record_seq + 1
  == block_set_chunk_count
     + wait_set_chunk_count
     + transfer_event_count
     + recovery_event_count
```

Intervals are maximal consecutive dropped data sequences with one reason.
Reason changes, nonconsecutive sequences, the next successful enqueue, or
close seal an interval. `loss_interval_seq` is contiguous from zero.

The exactly-last `profile_summary` contains
`ended_timestamp_ns`, `attempted_data_count`,
`written_block_set_chunk_count`, `written_wait_set_chunk_count`,
`written_transfer_event_count`, `written_recovery_event_count`,
`written_loss_interval_count`, `dropped_data_count`,
`dropped_control_count`, `first_data_record_seq`,
`last_data_record_seq`, `writer_failure_count`, `close_outcome`, and
`content_sha256`, plus the common envelope/profile digest. Counts are uint64;
`close_outcome` is `drained`, `timeout`, or `writer_failure`. When no data was
attempted, first/last are null; otherwise they are `0` and
`attempted_data_count - 1`.

The closed ledger equations are:

```text
attempted_data_count
  == written_block_set_chunk_count
     + written_wait_set_chunk_count
     + written_transfer_event_count
     + written_recovery_event_count
     + dropped_data_count

dropped_data_count
  == sum(written loss_interval.dropped_count)
```

Every missing data sequence is covered exactly once. A lost loss record or
summary increments `dropped_control_count` and invalidates the shard; no
summary fabricates a balanced ledger. `content_sha256` hashes in file order
the exact raw `profile_start`, successfully written profile data records, and
`loss_interval` records including LF, excluding only `profile_summary`.

Control/reserved capacity, writer ownership, deterministic batching,
nonwaiting producer enqueue, writer-failure accounting, and the 2000-ms close
deadline follow P0's algorithms with the profile-specific data categories and
equations above. The summary is exactly last. A profile shard is complete only
when its immutable close receipt is `drained + summary_written` and its content
digest verifies.

The run manifest starts from an independently frozen expected-process roster
and accepts only each process's `committed_shard_path` after close. A raw path,
glob, empty sentinel, late valid-looking file, or `filter(None)` construction
is forbidden.

## 7. Exact stage ownership and boundary

| Stage | Owner and committed observation boundary |
| --- | --- |
| `preempt` | `engine_core`: snapshot logical identity before free, but emit only after `_preempt_request` has committed `RUNNING -> PREEMPTED`, reset computed tokens, incremented `num_preemptions`, and prepended the request to waiting. |
| `restore_start` | rank-0 worker: immediately after the matching H2D `submit_load` is accepted. Scheduler mapping/allocation is not copy start. |
| `restore_done` | rank-0 worker: first successful `get_finished` observation for the same transfer, with positive bytes. This is a worker completion boundary, not scheduler visibility. |
| `scheduler_wakeup` | `engine_core`: the first later waiting traversal that consumes the exact `finished_recving` handoff, finishes `_update_waiting_for_remote_kv`, and promotes the request to `PREEMPTED`. |
| `requeue` | `engine_core`: an explicit, instrumented post-wakeup defer branch before admission. The initial prepend performed by preemption is not counted. |
| `admission` | `engine_core`: after the request is classified as resumed, appended to running, and committed to `RUNNING` with positive scheduled tokens. |
| `first_prefill_or_decode` | rank-0 worker profile child observation: immediately before the first real model-forward boundary whose exact scheduler roster contains `(runtime_request_id, recovery_epoch)`; record whether it is prefill or decode and reference the active base phase start. EngineCore `execute_model()` alone is dispatch, not this boundary, and the child does not move the frozen base boundary. |

The episode uses explicit predecessor IDs in the displayed chain. A requeue
chain connects wakeup to the first requeue, each requeue to the next, and the
last requeue to admission. With zero requeues, wakeup connects directly to
admission.

## 8. Requeue reasons

The closed reason vocabulary is:

- `lora_capacity`;
- `prefill_throttled`;
- `token_budget`;
- `encoder_budget`;
- `block_capacity`;
- `unclassified`.

`unclassified` is diagnostic-only and invalidates formal decomposition. A
branch that combines multiple possible causes must be split or must emit
`unclassified`; the adapter may not guess from queue state on a later pass.

Running-capacity and scheduler-pause checks occur before this request is
peeked, while connector lookup/inflight, transfer-budget, and encoder-cache
waits occur before successful H2D wakeup or are unreachable after restored
tokens are installed. They contribute to pre-wakeup waiting evidence, not to
the profile's post-wakeup `requeue_count`, and are intentionally absent from
this enum.

## 9. Communication specialty mapping dependency

The desired future base-trace mode, subject to a separate content-addressed
issue-2 mapping artifact and issue-2-authority approval, is:

```text
communication_mode=issue2:kv-recovery-v1alpha1
```

The recovery profile records this closed recovery-side observation vocabulary:

- transfer operations `d2h_preserve` and `h2d_restore`; and
- wait-set operation `transfer_wait`.

The future mapping may propose the corresponding base evidence codes
`issue2:kv-recovery-v1alpha1:d2h_preserve`,
`issue2:kv-recovery-v1alpha1:h2d_restore`, and
`issue2:kv-recovery-v1alpha1:transfer_wait`. Those names are not active base
evidence codes and do not constitute a closed issue-2 subtype/edge roster.
`d2h_preserve` and `h2d_restore` begin at accepted worker submission and end
at the matching successful device-transfer completion. They are productive
data movement under Draft v4.3 only when runtime job, direction, device, block
set, and nonduplicated operation match. `transfer_wait` is restricted to an
explicit worker `OffloadingWorker.wait(nonempty_job_ids)` call: it begins
immediately before that blocking call and ends immediately after return, and
references the sorted transfer IDs covered by the job set. Its bounded base
metadata carries `transfer_count` and `wait_set_id`, where `wait_set_id` uses
the run/process-scoped canonical construction in section 6.4. It is a
wait span, never productive copy, and it does not include scheduler
`WAITING_FOR_REMOTE_KVS` residence. The same source operation must not
materialize twice through task and communication tables.

For the H2D recovery pair, this profile supplies the following candidate
fragment for the separate issue-2 mapping artifact:

- emit engine-sample `communication_started` and `communication_done` with
  `component=external_evidence`, one new span ID, the same trace/lifecycle,
  `preemption_epoch=recovery_epoch`, and timestamps equal to the validated
  rank-0 submit/completion profile observations;
- bounded metadata carries `operation=h2d_restore`, `transfer_id`,
  `block_set_id`, `direction=h2d`, and positive done bytes;
- emit a same-trace `data_dependency` edge from the closing base `preempted`
  event to `communication_started`, using
  `issue2:kv-recovery-v1alpha1:h2d_restore`; and
- emit a same-trace `data_dependency` edge from `communication_done` to the
  next-epoch base `admission_started`, using the same evidence code.

The profile `restore_start`/`restore_done` records reference those exact base
event IDs. Missing span endpoints, either edge, the epoch `e -> e+1` relation,
or any identity mismatch makes the episode incomplete.

The proactive asynchronous D2H store and worker-internal transfer wait do not
yet have a complete base execution-parent/return edge mapping. Their profile
records and run-scoped wait-set chunks preserve the facts, but they cannot be
promoted to valid base communication children merely by matching timestamps.
The separate issue-2 artifact must define or reject D2H/wait base spans,
execution parents, return/data-dependency edges, duplicate suppression,
evidence levels, and completeness rules, and must bind this profile digest.
Until that artifact exists, even the H2D fragment above is non-activatable.

Remygred may approve the recovery profile bytes and endorse preparation of the
separate mapping, but that action alone does not freeze the `issue2:*`
namespace. Activation requires a complete mapping artifact with its own digest
and a second explicit approval from the issue-2 contract owner or another
authority explicitly delegated for this specialty profile. That artifact must
cite the approved recovery-profile digest and close the complete subtype/edge
roster. Until both records exist, every connector-enabled tiering/offload trace
remains `BLOCKED` with
`communication_subtype_unfrozen`. HBM-only with no connector may retain
`communication_mode=none`; it normally has no recovery episode and is a
control, not positive recovery evidence.

## 10. Clock and offline conversion

All host lifecycle timestamps remain uint64 `CLOCK_MONOTONIC` nanoseconds on
wire. The first version requires one canonical same-host `clock_domain_id` for
the engine core and rank-0 worker. Cross-domain or cross-host episodes fail
closed.

After validation, let `origin_ns` be the `preempt` timestamp. The PR #4 adapter
sets each `timestamp_ms` to:

```text
(timestamp_ns - origin_ns) / 1_000_000
```

It maps:

- `runtime_request_id` -> `KVRecoveryEvent.request_id`;
- `engine_lifecycle_id` -> `sequence_id`;
- profile stage -> the matching `KVRecoveryStage`;
- canonical logical block IDs -> `block_ids` for both restore milestones;
- successful H2D done bytes -> `bytes_moved`; and
- reasoned requeue code -> `reason`.

The adapter validates integer-nanosecond ordering before float conversion. It
must preserve equal adjacent timestamps and must not repair inversion by
sorting across identities or clock domains. The offline model's `copy_ms` is
the worker-observed H2D submit-to-done host interval; supplemental
`device_duration_ns` must be reported separately and cannot silently replace
it.

## 11. Completeness and fail-closed rules

A valid episode requires all of the following:

1. exactly one complete base trace and exactly one complete profile episode;
2. one stable request, trace, engine lifecycle, sample, positive recovery
   epoch, and episode ID across all episode-associated records; proactive
   D2H-only records may use the explicitly allowed null epoch/episode and do
   not enter the seven-stage decomposition;
3. one each of the six unique milestones and zero to 64 ordered requeues;
4. monotonic order
   `preempt <= restore_start <= restore_done <= scheduler_wakeup <= requeues
   <= admission <= first_compute`;
5. one nonempty identical logical block set at H2D start and done;
6. one successful H2D transfer with positive bytes and no retry or failure;
7. the required base event IDs, `base.preemption_epoch + 1 ==
   recovery_epoch`, profile predecessor links, worker-child association, and
   complete wait-set membership;
8. exact request/epoch membership in the first-compute scheduler roster;
9. the Remygred-approved profile digest, separately approved issue-2 specialty
   mapping, implementation family, resolved configuration hash,
   runtime/device pins, and expected process roster;
10. no data/control loss, invalid record, unknown field, duplicate identity,
    incomplete summary, missing close receipt, unexpected shard, or mixed
    clock domain.

Missing, duplicate, inverted, over-bound, privacy-invalid, or inconsistent
evidence rejects the entire episode. Serving remains fail-open; evidence fails
closed. A rejected episode may be retained as a diagnostic artifact with the
specific reason, but it cannot be adapted into a plausible PR #4 timeline,
used for M0 scoring, or counted as a performance point.

## 12. Evidence and claim boundary

A complete controlled trace proves capture coverage for one recovery episode.
It does not prove:

- hardware idle under any circumstance, or a causal idle explanation without
  the applicable approved evidence and intervention rules;
- that tiering is faster than HBM-only;
- that copy overlaps compute;
- a throughput, TTFT, TPOT, or tail-latency improvement;
- representativeness across capacity/workload points; or
- blind M0 localization accuracy.

Those claims require the later matched experiments, independent service
lifecycles, correctness gates, raw artifacts, environment manifest, and
counterfactual rules recorded in repository `AGENTS.md`.

## 13. Approval record proposed for this candidate

Profile-owner approval must cite the final SHA-256 and explicitly accept or
replace each decision:

1. profile ID and separation from `rlp.trace/v1alpha1`;
2. one-host, one-rank, one-successful-restore scope;
3. internal request ID, canonical lifecycle sequence, recovery epoch, transfer,
   and logical block identities;
4. the epoch `e -> e+1` relation and seven stage owners/boundaries, especially
   worker-owned restore done, scheduler wakeup, completed admission, and the
   worker child observation that does not move the base compute boundary;
5. the bounded record grammar, wait-set membership, profile-specific loss
   ledger, process receipts, completeness, and fail-closed rules;
6. the requeue reason vocabulary and diagnostic-only `unclassified` value;
7. endorsement of the proposed operation labels, H2D mapping fragment, v4.3
   dependency, and preparation of a separate content-addressed issue-2 mapping,
   while acknowledging that non-`none` remains blocked pending its complete
   subtype/edge roster and issue-2-authority approval; and
8. the implementation-family decision: runtime-core
   `OffloadingConnector/TieringOffloadingSpec` with
   `recompute_scheduler_enable=false`, or a separately reviewed compatible
   runtime/device pair.

Approval of this document alone does not approve a resolved benchmark #134
configuration or a runtime/device patch. Those are separately content-
addressed compatibility and experiment decisions. It also does not activate
the proposed communication mode: the issue-2 contract owner or an explicitly
delegated specialty authority must separately approve a complete mapping
artifact with its own digest that binds this recovery-profile digest.
