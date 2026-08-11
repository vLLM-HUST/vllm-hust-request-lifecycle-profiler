# Scheduler Profile Wire Contract — Owner Review Candidate

- Status: `owner_review_candidate`
- Evidence status: `NOT_IMPLEMENTED`
- Wire schema: `rlp.scheduler/v1alpha1`
- Profile stream: `scheduler`
- Configuration: `contracts/p1/scheduler-profile-config.v1alpha1.json`
- Parent architecture: `contracts/p1/scheduler-profiler-infra.v0-draft.md`
- PR-I0 evidence authority: `intellistream/ascend-llm-realworkload-prof#30`

This document freezes the proposed scheduler wire bytes and the offline
admission semantics required by PR-C1. It does not modify the owner-frozen
`rlp.trace/v1alpha1` bytes, implement an exporter, authorize runtime hooks, or
promote any queueing-mechanism evidence. The machine-readable configuration and
the approval candidate bind the numeric choices in this document. Only an
explicit owner reply accepting their exact digests can authorize PR-I1 or
PR-I2.

## 1. Supported profile and fail-closed boundary

Formal v1 input is restricted to one host, one visible Ascend device, rank 0,
decoder-only generation, one prompt, `n=1`, eager mode, `UniProcExecutor`, and
all TP/PP/DP/DCP sizes equal to one. Async scheduling, speculation,
multimodal input, graph capture, a KV/EC transfer connector, multiple in-flight
batches, and any unreceipted runtime source are unsupported.

The effective runtime values must match the `runtime_profile` object in the
machine-readable configuration. A mismatch may produce bounded diagnostic
records, but it makes the scheduler shard and every derived join ineligible for
formal evidence. The producer never changes scheduler decisions or serving
output in order to obtain evidence.

## 2. Encoding and primitive domains

Every record is one strict JSON object encoded as UTF-8 with object keys sorted
by UTF-16 code-unit order, compact separators, no insignificant whitespace, no
BOM, and exactly one trailing LF byte. Property ordering and string escaping
follow RFC 8785; integers instead use the exact unsigned domains below and are
emitted as base-10 digits without an IEEE-754 conversion. JSON member names are
unique. Unknown fields, NaN, Infinity, negative zero, floats, and lone Unicode
surrogates are forbidden. The encoded record including LF is at most `8192`
bytes.

Integer validation is exact: a JSON boolean is never an integer. `uint32` is
`0..4294967295`; `uint64` is `0..18446744073709551615`. Timestamps are uint64
nanoseconds from `CLOCK_MONOTONIC` unless a field explicitly says realtime.
Durations and ordering are computed only from timestamps with one approved
clock-domain identity.

The common members of every record are exactly:

| Field | Type and value |
| --- | --- |
| `schema_version` | exact string `rlp.scheduler/v1alpha1` |
| `record_type` | one value in Section 4 |
| `process_uuid` | 32 lowercase hexadecimal characters |
| `profile_stream` | exact string `scheduler` |
| `experiment_run_uuid` | canonical lowercase UUID with hyphens |
| `engine_instance_id` | 32 lowercase hexadecimal characters, generated once per EngineCore instance |

Every data record additionally has `record_seq` (uint64). It is allocated
atomically in producer-observation order before validation, serialization, or
enqueue. It is an audit sequence, never a causal edge. `scheduler_start`,
`loss_interval`, and `scheduler_summary` are control records and do not consume
`record_seq`.

## 3. Identity and relation representation

Entity counters are independent uint64 counters, start at zero, and never
reuse a value in one scheduler shard. Their canonical IDs are:

```text
schedule_cycle_id = process_uuid + ":scheduler:cycle:" + cycle_seq
logical_batch_id  = process_uuid + ":scheduler:batch:" + batch_seq
execution_step_id = process_uuid + ":scheduler:step:"  + execution_step_seq
```

Embedded integers use unsigned base-10 ASCII with no leading zero except `0`.
Each ID is at most 80 ASCII bytes. A complete initial-profile cycle has exactly
one logical batch and exactly one execution step. Relations are not inferred
from equal counters: the cycle names `logical_batch_id`; the batch names both
`schedule_cycle_id` and `execution_step_id`; both step records name the batch.

The initial profile permits at most one execution step in flight. A duplicate
ID, a non-bijective relation, a skipped relation, a second open step, or a
relation crossing process/run/engine scope invalidates the shard. A later
profile may change cardinality only with a new wire version and capacity proof.

## 4. Closed record roster

`record_type` is exactly one of:

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

The first record is exactly one `scheduler_start`; the final record is exactly
one `scheduler_summary`. Every other record appears between them.

### 4.1 `scheduler_start`

Additional members are exactly:

```text
started_monotonic_ns                 uint64
clock_source                         "CLOCK_MONOTONIC"
clock_domain_id                      32 lowercase hex
scheduler_process_uuid               equal to process_uuid
executor_target_process_uuid         equal to process_uuid for approved UniProc
runtime_core_commit                  40 lowercase hex
device_plugin_commit                 40 lowercase hex
parent_protocol_commit               40 lowercase hex
scheduler_profile_contract_sha256    64 lowercase hex
scheduler_profile_config_sha256      64 lowercase hex
multistream_overlay_sha256           64 lowercase hex
runtime_profile_id                   printable ASCII, 1..96 bytes
limits                               exact object below
```

`limits` is byte-semantically equal to the complete `wire_limits` object in the
machine-readable configuration, including the artifact/disk limits, exact shard
path template, and scope. The start-record digests must match the
manifest-approved bytes; a self-reported digest is never authority by itself.

### 4.2 `schedule_cycle`

Additional members are exactly:

```text
record_seq
cycle_seq
schedule_cycle_id
logical_batch_id
cycle_start_monotonic_ns
cycle_end_monotonic_ns
cycle_outcome                         completed | failed
waiting_engine_request_count_before  uint32
running_engine_request_count_before  uint32
waiting_engine_request_count_after   uint32
running_engine_request_count_after   uint32
configured_batched_token_budget      uint64
effective_batched_token_budget       uint64
configured_active_sequence_cap       uint32
effective_active_sequence_cap        uint32
token_budget_summary                 exact object in Section 5
active_sequence_cap_summary          exact object in Section 5
```

The end is not before the start. Formal evidence requires `completed`. Waiting
counts include both the primary waiting queue and `skipped_waiting`; running
counts are the length of the scheduler running collection at the respective
audited boundaries. These are `engine_request` counts under `n=1`, not sequence
or request-group aliases.

### 4.3 `logical_batch`

Additional members are exactly:

```text
record_seq
batch_seq
logical_batch_id
schedule_cycle_id
execution_step_id
logical_batch_kind                    work | empty_control
scheduled_token_count                 uint64
scheduled_engine_request_count        uint32
prefill_token_count                   uint64
decode_token_count                    uint64
device_attribution_eligible           boolean
```

Always:

```text
scheduled_token_count = prefill_token_count + decode_token_count
```

`work` requires a positive scheduled token count and
`device_attribution_eligible=true`. `empty_control` requires all three token
counts to be zero and `device_attribution_eligible=false`; it remains linked to
its dispatched execution step and is never deleted from completeness audits.
`scheduled_engine_request_count` is the number of entries in the approved
SchedulerOutput request-to-scheduled-token mapping. Prefix-cache tokens not
scheduled for compute do not contribute; chunked prefill contributes only the
current chunk. Speculative tokens are unsupported.

### 4.4 `execution_step_start`

Additional members are exactly:

```text
record_seq
execution_step_seq
execution_step_id
logical_batch_id
scheduler_process_uuid               equal to process_uuid
executor_target_process_uuid         equal to process_uuid in approved profile
rank_id                               uint32, exactly 0
device_id                             uint32, exactly 0
dispatch_monotonic_ns                 uint64
dispatch_kind                         uniproc_execute_model
```

This is the host observation immediately before the approved executor dispatch.
It is not a device-task start.

### 4.5 `execution_step_end`

Additional members are exactly:

```text
record_seq
execution_step_seq
execution_step_id
logical_batch_id
final_result_monotonic_ns             uint64
execution_outcome                     completed | failed | cancelled
sampling_status                       included_in_envelope | not_applicable
```

The end uses the same execution counter/ID and occurs after its start. For the
approved generation route it is observed only after the final model result and
any separate sampling call required for that result. Formal evidence requires
`completed`; `sampling_status` must reflect the audited runtime route.

### 4.6 `clock_bridge_sample`

Additional members are exactly:

```text
record_seq
sample_sequence                       uint64, contiguous from zero
clock_domain_id                       equal to scheduler_start
monotonic_before_ns                   uint64
realtime_ns                           uint64 CLOCK_REALTIME
monotonic_after_ns                    uint64
```

`monotonic_before_ns <= monotonic_after_ns`. Samples are acquired outside the
scheduler cycle at the configured cadence. They use the scheduler data ledger
and never create a separate unbounded file or queue.

### 4.7 `loss_interval`

Additional members are exactly:

```text
loss_interval_seq                     uint64, contiguous from zero
loss_interval_id                      process_uuid + ":scheduler:loss:" + seq
reason                                serialization_failure | queue_overflow |
                                      writer_failure | close_timeout
first_dropped_record_seq              uint64
last_dropped_record_seq               uint64
dropped_count                         uint64
schedule_cycle_count                  uint64
logical_batch_count                   uint64
execution_step_start_count            uint64
execution_step_end_count              uint64
clock_bridge_sample_count             uint64
first_observed_monotonic_ns            uint64
last_observed_monotonic_ns             uint64
```

The five type counts sum to `dropped_count`, which equals the inclusive record
sequence range size. Maximal consecutive losses with the same reason form one
interval. Any written loss interval makes the shard diagnostic-only.

### 4.8 `scheduler_summary`

Additional members are exactly:

```text
ended_monotonic_ns                    uint64
attempted_data_count                  uint64
written_schedule_cycle_count          uint64
written_logical_batch_count           uint64
written_execution_step_start_count    uint64
written_execution_step_end_count      uint64
written_clock_bridge_sample_count     uint64
written_loss_interval_count           uint64
dropped_data_count                    uint64
dropped_control_count                 uint64
first_data_record_seq                 uint64 or null
last_data_record_seq                  uint64 or null
writer_failure_count                  uint64
close_outcome                         drained | timeout | writer_failure
content_sha256                        64 lowercase hex
```

Written data counts plus dropped data equal `attempted_data_count`. With no
attempted data both sequence endpoints are null; otherwise they are `0` and
`attempted_data_count-1`. `content_sha256` hashes exact LF-terminated bytes in
file order from `scheduler_start` through the last non-summary record and
excludes the summary. Formal completeness requires `drained`, zero loss/drop/
writer failure, balanced relations, a valid digest, and a committed-shard
receipt.

## 5. Fixed-size constraint summary

No per-evaluation wire record is allowed. Each cycle contains exactly one
token-budget summary and one active-sequence-cap summary. Each is lossless for
the approved aggregate binding queries, has fixed bucket cardinality, stores no
request identity, and satisfies:

```text
evaluated_count = accounted_count + unclassified_count
accounted_count = sum(bucket.count)
```

Common summary members are exactly:

```text
constraint_id
gate_status                 evaluated | not_evaluated | missing
not_evaluated_reason        no_candidates | gate_not_reached |
                            constraint_disabled | not_applicable | null
evaluated_count             uint32
accounted_count             uint32
unclassified_count          uint32
buckets                     fixed ordered array
first_unclassified_witness  witness or null
```

For `evaluated`, the reason is null and `evaluated_count>0`. For
`not_evaluated`, all counts and buckets are zero, witnesses are null, and the
reason is nonnull. `missing` is an explicit diagnostic state with zero counts,
null reason, and no witnesses; it never passes formal evidence. An unclassified
evaluation preserves its deterministic first witness but also fails formal
constraint completeness.

Each bucket has exactly `queue`, `mode`, `count`, and `first_witness`. `count=0`
iff the witness is null. Otherwise the witness is the first observation in the
pinned loop order. All legal buckets are present once in the following order:

```text
token budget:
  running/not_limited, running/clipped, running/stopped_no_chunk,
  waiting/not_limited, waiting/clipped, waiting/stopped_no_chunk,
  skipped_waiting/not_limited, skipped_waiting/clipped,
  skipped_waiting/stopped_no_chunk

active sequence cap:
  running/not_limited, running/stopped_at_cap,
  waiting/not_limited, waiting/stopped_at_cap,
  skipped_waiting/not_limited, skipped_waiting/stopped_at_cap
```

A token-budget witness contains exactly:

```text
evaluation_ordinal uint32
candidate_tokens_at_gate uint64
token_budget_before_at_gate uint64
granted_tokens_at_budget_gate uint64
running_count_at_budget_gate uint32
waiting_count_at_budget_gate uint32
effective_cap_at_budget_gate uint32
```

An active-cap witness contains exactly:

```text
evaluation_ordinal uint32
cap_gate_waiting_count uint32
token_budget_at_cap_gate uint64
running_count_at_cap_gate uint32
effective_cap_at_gate uint32
```

An unclassified witness uses the applicable witness roster plus exact string
`reason_code`, whose closed values are `unmapped_branch` and
`invalid_observation`. Runtime observations report facts only. The analyzer
derives each constraint independently as `BINDING` if any limiting bucket is
nonempty, `NON_BINDING` if at least one evaluation occurred and every bucket is
`not_limited`, and `INDETERMINATE` otherwise. If both constraints are binding,
exclusive mechanism attribution is `CONFOUNDED`, not whichever branch happened
to be observed last. Legacy booleans may be derived only in a labelled lossy
view; `INDETERMINATE` is never coerced to false.

## 6. Analyzer-derived run identity authority

`experiment_run_uuid` names an experiment. `traceloom_run_id` names one
analyzer materialization. One experiment may map to multiple materializations;
the two identifiers are not generally equal.

The new authority is `rlp.traceloom-run/v1alpha1`. Its input is an object named
`metadata_without_run_id` with exactly these top-level members:

```text
analyzer
contract_id
device_materializations
experiment_run_uuid
idle_evidence
materialization_uuid
options
scheduler_profile
source_label
```

Nested member rosters are exact:

```text
analyzer = {commit, repository}
idle_evidence = {contract_sha256, contract_version}
scheduler_profile = {
  config_sha256, contract_sha256, manifest_sha256, overlay_sha256
}
options = {label, revision, strict, tags}
device_materializations[] = {
  device_id, rank_id, source_inventory_sha256
}
```

Git commits are 40 lowercase hex; digests are 64 lowercase hex; UUIDs are
canonical lowercase with hyphens. `repository`, contract/version identifiers,
and tags are 1..128 Unicode scalar-value strings; `label` is the same or null;
`strict` is boolean; `revision` is an integer in the I-JSON exact range
`[-9007199254740991, 9007199254740991]`. Floats and lone surrogates are
forbidden. Tags preserve input order. Device entries are sorted by
`(device_id, rank_id, source_inventory_sha256)` and are unique.

The member `run_id` is forbidden. Raw/absolute `source_path` is forbidden;
content inventory digests provide portable source identity. Canonical bytes are
RFC 8785 JCS over the restricted domain above, including UTF-16 code-unit
property ordering. Then:

```text
traceloom_run_id = lowercase_hex(SHA-256(canonical_bytes))
```

Omitted and null members are distinct: because the roster is exact, omission
is invalid while `options.label=null` is legal. Array order is significant
except for the pre-sorted device array. Golden vectors cover Unicode, safe
integer boundaries, booleans, null, arrays, key order, omission, and one-byte
mutation through two independent canonicalizers.

Migration from the audited historical analyzer identity uses a separate object
with schema `rlp.traceloom-run-mapping/v1alpha1` and exactly:

```text
experiment_run_uuid
materialization_uuid
traceloom_run_id
legacy_contract_path
legacy_contract_sha256
legacy_analyzer_run_id
source_inventory_sha256
mapping_sha256
schema_version
```

`legacy_analyzer_run_id` may be null when no valid old materialization exists.
`schema_version` is exactly `rlp.traceloom-run-mapping/v1alpha1`.
`legacy_contract_path` is a repository-relative portable path of 1..256 Unicode
scalar values: it cannot start with `/`, contain a `..` component, or contain a
backslash. Identity and inventory values are lowercase SHA-256; the legacy ID
is either lowercase SHA-256 or null. `mapping_sha256` is the new run-identity
canonicalizer digest over the mapping object without `mapping_sha256`. One
`(experiment_run_uuid,
materialization_uuid)` maps to exactly one new identity and at most one legacy
identity. A conflicting mapping, silent recomputation under new rules, or
one-to-one experiment assumption fails closed. This mapping does not retroactively
declare the Draft v4.3 prose and current analyzer implementation identical.

## 7. Runtime-to-profiler process binding receipt

The binding is a separate strict JSON receipt, not a scheduler hot-path record.
Its schema is `rlp.runtime-profiler-process-binding/v1alpha1` and its exact
members are:

```text
schema_version
runtime_profiler_process_binding_id
experiment_run_uuid
process_uuid
runtime_pid
runtime_pid_namespace_inode
runtime_nspid_vector
runtime_boot_id_sha256
runtime_proc_start_ticks
executor_role
rank_id
local_rank_id
device_id
profiler_visible_global_pid
profiler_pid_namespace_inode
profiler_pid_representation
profiler_context_ids
runtime_capture_receipt_sha256
profiler_source_inventory_sha256
binding_source
binding_status
reason_codes
captured_before_admitted_work
receipt_sha256
```

PIDs, rank, local rank, and device are uint32; namespace inode, proc start ticks,
NSpid entries, and context IDs are uint64. `runtime_nspid_vector` and sorted
unique `profiler_context_ids` each contain 1..8 values. Initial
`executor_role=engine_core_uniproc_worker`,
`profiler_pid_representation=host_global`, and
`binding_source=application_owned_msprof_task_global_pid_context_id`.
`binding_status` is `exact`, `ambiguous`, `unmatched`, or `unsupported`.

The binding ID is lowercase SHA-256 of the canonical object containing, in the
closed roster shown below, the members from `experiment_run_uuid` through
`profiler_context_ids` in the receipt. Object serialization still uses the
canonical key order from Section 2; the displayed order defines membership,
not serialization order.

```text
experiment_run_uuid, process_uuid, runtime_pid,
runtime_pid_namespace_inode, runtime_nspid_vector, runtime_boot_id_sha256,
runtime_proc_start_ticks, executor_role, rank_id, local_rank_id, device_id,
profiler_visible_global_pid, profiler_pid_namespace_inode,
profiler_pid_representation, profiler_context_ids
```

`receipt_sha256` hashes the whole canonical receipt without itself. An exact
binding requires capture
inside the executor after process start and before admitted work, matching boot/
namespace/NSpid/start evidence, one compatible profiler PID, and the complete
bounded context set retained from raw TASK rows. PID, rank, device, or time
overlap alone never creates process identity. PID reuse, a missing start
identity, a namespace ambiguity, a truncated context set, or competing PIDs
cannot be exact.

## 8. Clock model and execution-anchor join

Bridge samples use midpoint
`floor((monotonic_before_ns+monotonic_after_ns)/2)`. Segments and validity use
the exact `clock_bridge` values in the configuration: eight samples minimum,
one-second cadence, two-second maximum gap, 100-us maximum bracket width,
5-ms realtime-jump split, 100-ppm maximum adjacent drift, 200-us immediate-
neighbor holdout residual, zero extrapolation, and summed endpoint uncertainty.
An endpoint above 500 us uncertainty is unsupported.

An execution step joins only inside one exact process binding. `exact_identity`
requires a profiler-visible step-ID handoff and unique anchor. The admitted
correlation predicate is the configured robust containment inequality plus at
least 0.95 nominal containment, valid run/rank/device/clock scope, and exactly
one candidate. Nearest-time selection is forbidden.

Each attempted join is exactly one of `exact_identity`,
`calibrated_correlated`, `ambiguous`, `unmatched`, or `unsupported`. It retains
the selected nullable anchor, candidate count, candidate relation, anchor
source, process-binding ID/status, clock model, and uncertainty. Up to eight
candidate rows are retained. More than eight are not truncated: retain no
candidate rows, record the exact observed count and overflow flag, set
`unsupported`, and fail evidence closed.

## 9. Overall and tail coverage

For any half-open window `W`, construct the eligible scheduler-step denominator
before examining profiler matches. It contains every complete positive-duration
step in the supported run/engine scope whose linked batch is `work`, is device-
eligible, and intersects `W`. Missing bindings, clocks, anchors, or profiler
coverage remain in this denominator.

```text
step_join_coverage(W)
  = admitted eligible step count / eligible step count

execution_duration_join_coverage(W)
  = measure(union(admitted step envelope intersect W))
    / measure(union(all eligible step envelopes intersect W))
```

Intervals are overlap-safe half-open unions. A zero denominator is
`UNDEFINED_FAIL_CLOSED`. Counts and durations are never averaged together or
reported as request coverage.

The overall window is manifest-declared before profiler matching. The tail
cohort uses complete normal `n=1` lifecycle requests and TTFT defined as
`first_token - initial queued`. Sort eligible TTFT values ascending, take the
nearest-rank `ceil(0.95*N)` value, and include every tie at or above it. Each
selected window is `[initial_queued, first_token)`; `W_tail` is their union
intersected only with the main analysis window. It is not clipped to scheduler
activity, profiler availability, or successful joins and is not called the
Queue phase. Failure to map a selected interval makes tail coverage undefined.

Formal thresholds are exact in the configuration. Overall requires at least
100 steps/1 s union, step coverage 0.99, duration coverage 0.995, ambiguous
fraction at most 0.005, unmatched at most 0.01, and unsupported zero. Tail
requires at least 20 steps/100 ms union, step coverage 0.95, duration coverage
0.98, ambiguous at most 0.01, unmatched at most 0.05, and unsupported zero.

## 10. Boundedness proof

Each cycle produces at most four data records: one finalized cycle, one batch,
one step start, and one step end. Clock samples add at most 1801 records to an
1800-second formal run. The admitted cycle-rate bound is 40 in every rolling
second, twice the measured PR-I0 maximum. For a 2-second writer-service gap and
safety factor two:

```text
cycle_burst_records = 40 * 2 * 4 * 2 = 640
clock_records_in_gap <= 3
data_capacity_records = 1024 >= 643
```

There are 64 separately reserved loss-interval slots. `scheduler_start` and
`scheduler_summary` are written through dedicated out-of-band control paths and
are the additional two records in the artifact bound. With 8192 bytes per
record:

```text
max_queued_bytes = (1024 + 64) * 8192 = 8,912,896
max_cycles = 1800 * 40 = 72,000
max_data_records = 72,000 * 4 + 1,801 = 289,801
artifact_bytes_max = (289,801 + 64 + start + summary) * 8192
                   = 2,374,590,464
disk_free_required = artifact_bytes_max + 67,108,864
                   = 2,441,699,328
```

The writer batches at most 128 records or 524,288 bytes, targets 100 ms, and
must never exceed the 2-second admitted service-gap measurement. Close has one
5-second deadline. Exact-bound admission succeeds; one-byte/one-record disk or
queue insufficiency rejects formal collection before work. Rotation and a
second scheduler shard for the same `(process_uuid, profile_stream)` are
unsupported. PR-I6 must measure that the implementation satisfies the service-
gap and overhead assumptions; this arithmetic alone is not an overhead proof.

## 11. Shard and manifest semantics

The exact scheduler path is
`<base>.rlp-scheduler.<process_uuid>.jsonl`, opened create-exclusive,
append-only, mode `0600`. `<base>` is a manifest-owned path in an already
validated exporter directory, not a glob or user-selected stream identity.
There is exactly one shard and sequence for `(process_uuid, scheduler)`.

The pre-run manifest declares the logical lifecycle/scheduler process-profile
roster. A post-launch receipt maps each role to its actual process UUID and
committed shard. Expected shards are never discovered from observed files.
Formal scheduler-profiler evidence requires every lifecycle/scheduler pair,
binding receipt, start/summary/digest, and relation to pass independently.
One valid stream never repairs another.

## 12. Approval record

The owner approval must cite exact SHA-256 digests and explicitly accept or
replace:

1. the record encoding, schemas, IDs, relations, zero-token behavior, and
   fixed constraint summaries;
2. the supported runtime profile and exact process-binding receipt;
3. the corrected analyzer-derived run identity and legacy migration mapping;
4. the clock, robust join, candidate overflow, and process-scope rules;
5. the overall/tail populations, denominators, minimum populations, and
   numeric thresholds;
6. every queue, byte, control, artifact, disk, writer-gap, and close limit;
7. the exact multi-stream overlay and unchanged lifecycle/KV-recovery bytes;
8. the rule that approval authorizes only subsequent default-off PR-I1/PR-I2
   implementation work, not runtime activation, NPU work, scientific evidence,
   a mechanism claim, merge, or M0.

Until that approval exists, this file remains an owner-review candidate and
all implementation/evidence gates remain false.
