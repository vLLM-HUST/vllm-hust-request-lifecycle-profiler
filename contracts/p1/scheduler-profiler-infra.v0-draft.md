# Scheduler Profiler Infrastructure — Route B Draft

- Status: `draft`
- Evidence status: `NOT_SCIENTIFIC_EVIDENCE`
- Route: `B — experiment-owned cross-source composition`
- Initial wire: `rlp.scheduler/v1alpha1`

This document replaces the earlier proposal that assigned scheduler-profile
ingestion, cross-database identity, and scheduler-to-device attribution to
TraceLoom. Route B keeps the scheduler producer local and bounded, keeps
TraceLoom's default one-source analysis boundary, and makes the experiment
repository the only authority that may compose multiple profile sources.

The architectural rule is:

> The scheduler profiler produces process-local scheduler facts. Cross-profile
> source identity and composition are performed by the experiment repository
> from an explicit run manifest.

No record or timestamp proximity may silently turn that rule into a global
identity or causal claim.

## 1. Scope and claim boundary

The initial profile records aggregate scheduler decisions for the audited
single-host, synchronous, uniprocess runtime path:

- scheduler start and summary;
- schedule-cycle begin/end and outcome;
- logical batch composition, including zero-token control batches;
- execution dispatch and final-result boundaries;
- bounded token-budget and active-sequence-cap summaries;
- scheduler-local monotonic clock bridge samples; and
- loss, writer, close, and completeness evidence.

The supported conclusion is an **observed scheduler–runtime–device
association** after the experiment composer validates every input. The profile
does not by itself support:

- global scheduler-to-device exact identity;
- cross-database rank inference from TASK PID or context ID;
- topology reconstruction from process or timestamp similarity;
- a claim that a runtime wait caused device idle;
- device-idle root cause, idle causal attribution, or exact stall cause; or
- per-request admission or causal attribution from aggregate records.

Allowed terms include `profiler-visible runtime activity`,
`profiler-visible device work`, `runtime-device relation`, `visible gap`, and
`observed association`. `Device idle` is not an alias for a visible gap.

## 2. Repository ownership

### 2.1 Profiler plugin

The profiler plugin owns only scheduler-local evidence:

- the scheduler record schema and closed record roster;
- `schedule_cycle_id`, `logical_batch_id`, and `execution_step_id`;
- clock-domain metadata and bounded bridge samples;
- process-local loss and completeness accounting;
- one bounded writer/exporter per scheduler shard;
- disabled-by-default and serving-fail-open behavior; and
- source commits and configuration needed to interpret the shard.

The plugin receives the following opaque identity values from the experiment
launcher and records them without deriving or rewriting them:

```text
experiment_run_id
server_instance_id
process_instance_id
scheduler_shard_id
process_role
profile_stream = scheduler
```

Those values say which declared run/process/shard produced a scheduler record.
They do not say which profile database contains matching device work.

### 2.2 TraceLoom

TraceLoom keeps its default one-profile-source isolation boundary and owns:

- parsing one supported source profile database or source directory;
- local `RuntimeCall` observations;
- local `DeviceWork` observations;
- local `RuntimeDeviceRelation` rows;
- source-table/source-row provenance; and
- local `ambiguous`, `missing`, and `unsupported` states.

Runtime and device identifiers are interpreted only within that source. PID
and context values may be retained as local diagnostic metadata, but they are
not a cross-database process or rank identity authority. TraceLoom does not
select another database, rebuild a global process topology, ingest scheduler
shards by default, or assign a global experiment run identity.

### 2.3 Experiment repository

The experiment repository owns all cross-source authority:

- `campaign_id`, `cell_id`, `experiment_run_id`, and
  `server_instance_id`;
- the independently constructed process roster;
- `process_instance_id`, `process_role`, `rank`, and `device_id`;
- explicit scheduler-shard to run/process mappings;
- explicit raw-profile and `analysis.db` to process/rank/device mappings;
- source paths, SHA-256 digests, and the TraceLoom commit;
- composition of one scheduler shard with one or more analysis databases;
- namespacing of every database-local identifier by `profile_source_id`;
- clock-compatibility or accepted-calibration decisions;
- cross-database completeness and candidate preservation; and
- the final claim and evidence-promotion boundary.

An unlisted database cannot enter composition. A missing rank, process, SHA,
or clock decision is never filled from PID, context, filename, enumeration
order, or a nearby timestamp.

## 3. Identity model

All launcher-provided identifiers are bounded printable ASCII and opaque.
Their spelling carries no topology semantics. In particular, `P0` and `rank
0` are separate facts; neither may be parsed from the other.

The scheduler shard scope is:

```text
(experiment_run_id, server_instance_id,
 process_instance_id, scheduler_shard_id, profile_stream)
```

The complete scope is present in `scheduler_start`, `scheduler_summary`, and
the experiment run manifest. Data records carry `scheduler_shard_id` and may
inherit the remaining values from the validated start record. A reader must
first validate the complete shard before interpreting inherited scope.

Scheduler-local IDs have this form:

```text
<scheduler_shard_id>:cycle:<cycle_seq>
<scheduler_shard_id>:batch:<batch_seq>
<scheduler_shard_id>:step:<execution_step_seq>
<scheduler_shard_id>:loss:<loss_interval_seq>
```

They are unique only inside the scheduler shard. They are not TraceLoom IDs,
profile-source IDs, global execution IDs, or cross-run identities.

Within a composed result, database-local IDs are always namespaced:

```text
(profile_source_id, runtime_call_id)
(profile_source_id, device_work_id)
(profile_source_id, runtime_device_relation_id)
```

Thus `device_work_id=42` in `PS0` and `PS1` remains two distinct objects.

## 4. Scheduler entities

### 4.1 `schedule_cycle`

One cycle brackets exactly one audited call to `Scheduler.schedule`. It owns
the scheduler state observed before the call, the resulting state after the
call, the effective configuration values, and fixed-cardinality constraint
summaries. A cycle does not imply device work.

### 4.2 `logical_batch`

One completed cycle yields exactly one logical batch:

- `work`: positive scheduled tokens and at least one scheduled engine
  request; or
- `empty_control`: zero tokens and zero scheduled engine requests.

`runtime_device_relation_candidate_eligible` is true only for `work`. The
field means only that the experiment composer may attempt an observed
association. It does not mean device attribution already exists.

### 4.3 `execution_step`

An execution step brackets the host-observed dispatch and final-result
boundary associated with one logical batch. The v1 profile requires a
bijective cycle → batch → step relation, including the empty-control step.
The empty-control step is retained for ordering and completeness and is never
eligible for a runtime-device association.

## 5. Runtime and call-site prerequisite (PR-I0)

PR-I0 remains valuable for scheduler-local semantics. It must audit:

1. the exact `Scheduler.schedule` call sites;
2. cycle start and end boundaries;
3. `SchedulerOutput` creation;
4. execution dispatch;
5. final result and sampling boundaries;
6. synchronous and asynchronous differences;
7. maximum records per cycle and zero-token behavior;
8. supported/unsupported modes; and
9. exact source commits and file hashes.

PR-I0 does not require TraceLoom TASK PID/context retention. PID/context may
remain diagnostic metadata for one source database only.

The Route B PR-I0 exit condition is:

1. scheduler call sites are audited;
2. scheduler-local identity is stable;
3. the experiment launcher can create an independent process roster;
4. each scheduler shard binds an injected `process_instance_id`;
5. every profile source binds explicitly to process/rank/device through a run
   manifest; and
6. no cross-database identity depends on PID/context or timestamp guessing.

## 6. Clock evidence

The wire clock is uint64 `CLOCK_MONOTONIC` nanoseconds with a declared
`clock_domain_id`. A bridge sample records one bounded
monotonic-before/realtime/monotonic-after bracket. The producer records facts;
it does not calibrate another profile source or declare a global time axis.

The experiment composer may compare a scheduler window with one analysis
source only when:

- both sides declare the same compatible clock domain; or
- the run manifest contains an explicit accepted calibration for that exact
  `(scheduler_shard_id, profile_source_id)` pair.

A compatible or calibrated clock can support `correlated`; it cannot promote
timestamp containment to `exact`.

## 7. Composition relation levels

The experiment composer uses this closed status roster:

- `exact`: both producer sides carry the same explicit, stable execution
  identity under a supported contract;
- `correlated`: explicit run/process/rank mapping, compatible clock or accepted
  calibration, and one unique legal time-contained local relation;
- `ambiguous`: two or more legal candidates; every candidate is retained;
- `unmatched`: the required inputs are supported but no candidate exists; and
- `unsupported`: an explicit mapping, clock decision, required local relation,
  or supported schema is absent.

Nearest-timestamp selection is forbidden. A correlation must remain named
`correlated`; it is not a provider exact-submission edge. Candidate overflow
is also `unsupported`, never silent truncation.

## 8. Loss and completeness

Each attempted data record consumes one monotonic `record_seq` before
validation, serialization, or enqueue. Every missing sequence in a shard that
reaches a summary is covered by one maximal loss interval. Loss is useful
diagnostic evidence, but the zero-loss completeness rule remains stricter:
any data loss, control loss, writer failure, timeout, digest mismatch, or
unexplained gap makes the whole scheduler shard ineligible for formal claims.

The experiment manifest is built from explicit committed-shard receipts, not a
glob. Every expected scheduler shard and profile source must be present and
hash-valid. Unknown extra files are audit findings and cannot be admitted by
discovery.

## 9. Bounded writer and disabled behavior

The producer path performs bounded validation, deterministic serialization,
and non-waiting enqueue only. File open/write/flush/close belongs to one writer
owner. Initialization, serialization, queue, writer, and close failures are
serving-fail-open and evidence-fail-closed.

When scheduler profiling is disabled:

- no scheduler shard is opened;
- no scheduler IDs or records are allocated;
- scheduling, execution, and outputs are unchanged; and
- the experiment manifest records that the stream was not activated rather
  than fabricating an empty complete shard.

## 10. Validation gates

The architecture requires the following CPU gates before runtime hooks:

- strict record/member/type and ID validation;
- start/summary scope equality and one-of-each cardinality;
- cycle/batch/step bijection and timestamp ordering;
- zero-token control retention;
- fixed-cardinality constraint accounting;
- exact record-sequence/loss coverage;
- deterministic content digest and record-size proof;
- disabled, overflow, writer-failure, and close-timeout behavior;
- manifest rejection for missing/duplicate process/rank/source mappings;
- SHA and analysis-source binding verification;
- database-local ID namespacing; and
- exact/correlated/ambiguous/unmatched/unsupported composer fixtures.

NPU collection, runtime activation, scientific evidence, mechanism claims,
and merge authorization remain separate gates.

## 11. PR sequence

### PR-I0 — runtime and call-site audit

Audits the scheduler-local semantics and proves the launcher/manifest mapping
seams. It does not require an analyzer PID/context PR.

### PR-C1 — wire and shard scope

Defines the local scheduler record schema, launcher-injected shard scope,
bounded writer limits, fixtures, and standalone verifier. It has no analyzer
run-identity or cross-database process-binding authority.

### PR-I1 / PR-I2 — exporter and runtime hooks

Implement the reviewed contract and audited call sites while preserving disabled
behavior and serving fail-open semantics.

### Experiment Route-B manifest and composer

Lives in the experiment repository. It validates the explicit process roster,
source hashes and bindings, then composes scheduler executions with namespaced
local TraceLoom relations while preserving all relation states and locators.

TraceLoom requires no scheduler ingestion or global-topology change for Route
B.

## 12. Architecture checklist

Review and CI must confirm all of the following:

- TraceLoom's default isolation boundary is one profile source;
- runtime/device IDs are local to one analysis database;
- PID/context is diagnostic-only and never cross-database authority;
- the experiment run manifest is the sole cross-source identity authority;
- the scheduler shard declares only its injected run/process/shard scope;
- no scheduler record selects or claims a profile database;
- all composed IDs retain a `profile_source_id` namespace;
- `exact` requires an explicit producer identity;
- timestamps can support only `correlated` and never causal/exact promotion;
- every ambiguous candidate is retained;
- missing mapping/calibration/local relation becomes `unsupported`;
- formal completeness fails closed on missing or unknown sources; and
- device-idle causal/root-cause claims are outside this route.

Passing this checklist does not make runtime collection scientific evidence
and does not establish a performance claim.
