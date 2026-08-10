# Scheduler Profiler Infrastructure — Architecture Review Candidate

- Status: `architecture_review_candidate`
- Evidence status: `NOT_IMPLEMENTED`
- Candidate future wire profile: `rlp.scheduler/v1alpha1`
- Base lifecycle schema: `rlp.trace/v1alpha1`
- Required shard overlay candidate:
  `rlp.trace-sharding/multi-profile-v1alpha1`
- Intended protocol repository:
  `intellistream/vllm-request-lifecycle-profiler-plugin`
- Offline analyzer: `vLLM-HUST/vllm-hust-perf-analyzer` / TraceLoom
- Authoritative experiment profile:
  `authoritative-910b2-qwen25-7b-v021`
- Decision-date basis: `2026-08-09`

This document is an architecture review candidate. It defines the scope,
semantic entities, repository boundaries, evidence model, and acceptance order
for scheduler-profiler infrastructure used by later aggregate queueing research.

It is deliberately not the complete `rlp.scheduler/v1alpha1` wire contract.
PR-I0 MUST first audit the exact pinned runtime call sites and cardinalities.
Only then may a separate, complete wire-contract candidate freeze record types,
field types and bounds, ID encodings, exporter limits, schema bytes, and owner
approval metadata.

Approval of this document authorizes architecture planning only. It does not
authorize hot-path implementation, NPU evidence collection, a queueing
mechanism experiment, or a performance or causal claim.

Normative terms MUST, MUST NOT, SHOULD, SHOULD NOT, and MAY are used in their
ordinary RFC-style sense.

## 1. Scope

### 1.1 Goal

The scheduler profiler must make the following evidence chain observable and
auditable:

```text
scheduler state and gate-local constraint evidence
                 |
                 v
           schedule cycle
                 |
                 v
       logical scheduler output
                 |
                 v
       host execution envelope
                 |
                 v
 calibrated profiler host/device evidence
```

The initial consumer is aggregate queueing attribution. The profiler must
support time-aligned analysis of:

- waiting and running engine-request counts;
- scheduled token and engine-request cardinality;
- scheduled prefill/decode composition;
- token-budget and active-sequence-cap gate evidence;
- scheduler decision duration;
- host execution dispatch-to-final-result duration;
- profiler-visible productive work and visible productive idle;
- existing TraceLoom idle-explanation categories;
- aggregate queue growth/drain and TTFT/ITL consequences supplied by the
  experiment repository.

### 1.2 Non-goals for the initial profile

The initial profile does not require or define:

- per-waiting-request admission causality;
- the full waiting set on every cycle;
- why request R was skipped in cycle C;
- full request-to-batch or request-to-execution membership;
- a token-budget or request-cardinality experiment matrix;
- a batch-volatility metric;
- `mu_eff` or a normalized service-work estimator;
- a mitigation controller;
- multi-host or multi-device attribution;
- speculative-decoding token semantics;
- a claim of hardware idleness from missing profiler-visible work;
- exact identity from temporal overlap alone;
- a paper-facing mechanism or causality claim.

A later deep-attribution profile may add request membership and per-request
admission reasoning. It requires a separately approved compatible extension,
capacity proof, and overhead result.

## 2. Authority and repository boundaries

### 2.1 Parent protocol repository

`intellistream/vllm-request-lifecycle-profiler-plugin` owns:

- this architecture candidate;
- the subsequent scheduler wire contract;
- the multi-profile shard overlay;
- bounded record construction and exporter integration;
- schema, contract, configuration, and approval identities;
- compatibility with base lifecycle identity and privacy rules;
- loss, completeness, disabled, and serving-fail-open semantics.

It does not own scheduler call sites that live in the runtime.

### 2.2 Core runtime and device-plugin repositories

PR-I0 decides the actual patch carrier for each observation. The ownership map
must distinguish at least:

- vLLM core scheduler and EngineCore call sites;
- vLLM-Ascend executor/model-runner call sites when required;
- a HUST core-runtime fork or compatibility branch, if used;
- a HUST Ascend integration/plugin fork, if used.

A call site in `vllm/v1/core/sched/scheduler.py` MUST NOT be attributed to the
Ascend plugin merely because the formal platform uses Ascend hardware.

The runtime implementation must live in a reproducible repository/branch or a
content-addressed patch set. An uncommitted installation edit is not a formal
runtime identity.

### 2.3 Analyzer repository

TraceLoom owns:

- scheduler-profile ingestion;
- normalized IR and sidecar tables;
- monotonic-to-realtime clock fitting;
- scheduler-to-device uncertainty composition;
- exact/correlated/ambiguous/unmatched/unsupported join classification;
- profiler execution-anchor construction;
- overlap-safe interval accounting;
- scheduler-window attribution using the existing idle taxonomy;
- SQL audit counters and fail-closed promotion.

TraceLoom remains offline. It does not launch workloads or change scheduling
policy.

### 2.4 Experiment repository

`intellistream/ascend-llm-realworkload-prof` owns:

- the authoritative platform profile;
- experiment run UUIDs and manifests;
- the predeclared logical process/profile roster;
- workload generation and client-side metrics;
- capacity calibration and load selection;
- mechanism experiment and statistical design;
- artifact retention and paper-facing claims.

The profiler may expose required observations but does not define the
intervention matrix or causal interpretation.

## 3. Runtime authority and PR-I0 prerequisite

The initial architecture targets only:

```text
hardware:      Ascend 910B2, one visible device/rank
vLLM:          ad7125a431e176d4161099480a66f0169609a690
vLLM version:  0.21 family
vLLM-Ascend:   80610e4438dba05011b05f89fc45d91e96992671
plugin version: 0.21.0rc1
engine:        vLLM V1
execution:     eager mode under the authoritative platform profile
```

The source of truth is
`ascend-llm-realworkload-prof/configs/platforms/authoritative_910b2_qwen25_7b.yaml`.

PR-I0 is a prerequisite to the complete wire-contract review. It must bind:

- authoritative platform/profile SHA-256;
- exact core and device-plugin commits;
- exact scheduler and relevant EngineCore source-file SHA-256 values;
- the approved adapter patch-set or implementation commit;
- clean-tree status or an explicitly approved dirty-overlay receipt;
- repository, file, method, process/thread, and observation point for every
  proposed field;
- supported and unsupported execution-mode matrix;
- cycle/output/execution cardinalities;
- zero-token scheduler-output behavior;
- final model-result boundary, including sampling when sampling occurs after
  `execute_model` result observation;
- gate-evaluation cardinality and maximum observations per cycle;
- exact prefill/decode counting variables;
- whether more than one batch/future can be in flight;
- the authority, input field set, canonicalization, digest encoding, and
  versioned contract location for the analyzer-derived run identity;
- the runtime process-to-profiler process/context binding source, including
  PID namespace and process-start identity, executor role, rank/device, and
  profiler-visible PID/context representation.

Commit identity alone is insufficient when a scheduler or adapter file differs
from the commit tree.

## 4. Dependency and compatibility architecture

### 4.1 Base lifecycle dependency

The scheduler profile depends on the approved semantics of
`rlp.trace/v1alpha1` and must not redefine:

- `trace_id` or `lifecycle_id`;
- lifecycle queue/admission/first-token boundaries;
- privacy restrictions;
- fail-open serving and fail-closed evidence behavior;
- lifecycle completeness.

When request-level linkage is present, `trace_id` and engine `lifecycle_id`
remain canonical.

Formal scheduler-profiler evidence additionally requires a destination-specific
base lifecycle adapter/conformance receipt for the pinned vLLM-0.21 runtime.
Approval of the older P0 semantics is not by itself proof that the current
runtime adapter is complete.

### 4.2 Multi-profile shard overlay

The architecture depends on
`contracts/p1/scheduler-profile-multistream-overlay.v0-draft.md`.

The proposed parent rule is:

> Each `(process_uuid, profile_stream)` pair owns one append-only shard and one
> monotonically increasing data-record sequence.

Lifecycle and scheduler streams share `process_uuid` but have separate
records, sequences, ledgers, summaries, digests, and receipts. The lifecycle
wire bytes remain unchanged.

The overlay and the eventual scheduler wire contract require new
content-addressed owner approval before this rule becomes active.

### 4.3 Run and process identities

The architecture distinguishes:

- `experiment_run_uuid`: assigned by the experiment repository before launch;
- `traceloom_run_id`: candidate scheduler-profile name for the analyzer
  `run_id` defined by `docs/idle_evidence_contract.md`, status
  `Draft v4.3 (proposed for M0 approval)`, architecture-candidate file SHA-256
  `8edb42b706b6cab14dfde2b109841cb8af090883c9ea86696ee779de21d0c9ed`.
  That draft defines the value as
  `lowercase_hex(SHA-256(JCS(metadata_without_run_id)))` under RFC 8785. The
  two names MUST denote identical bytes when this dependency is selected;
  this exact alias does not upgrade the draft to approved authority. PR-I0
  MUST reverify the path, version, digest, input metadata schema, and
  canonicalization authority. PR-C1 MUST either freeze that exact derivation
  or bind a separately versioned identity through an explicit
  content-addressed bijection and migration rule;
- `process_uuid`: one runtime process invocation, shared across streams;
- `engine_instance_id`: one EngineCore instance within the run;
- `scheduler_process_uuid`: the process that owns the schedule cycle and
  dispatch observation;
- `executor_target_process_uuid`: the worker/executor process selected by an
  approved runtime handoff, nullable only when PR-I0 proves in-process
  execution or the target is not yet observable;
- `profile_stream`: lifecycle, scheduler, or the registered `kv_recovery`
  compatibility stream; only streams enabled in the predeclared experiment
  roster are required for that run;
- `device_id` and `rank_id`: explicit even though the initial profile is
  single-device/rank.

The manifest must contain an explicit
`experiment_run_uuid <-> traceloom_run_id` mapping. Analyzer materialization
to the v4.3 tables uses the exact same value in their `run_id` column; an
implementation-selected second hash is forbidden. Scheduler wire fields named
only `run_id` or `run_uuid` remain forbidden because they omit the selected
contract scope. The mapping does not itself ratify the draft. If PR-I0 cannot
ratify the cited derivation unchanged, PR-C1 must freeze the explicit
content-addressed bijection/migration rule instead of claiming identity with
v4.3.

## 5. Initial supported profile

Formal v1 evidence is restricted to:

- single host;
- one visible Ascend device and rank;
- decoder-only generation;
- `n=1` and one prompt per request;
- eager execution;
- no speculative decoding;
- no cross-host or multi-device temporal disambiguation;
- no unsupported batch-queue or asynchronous scheduling mode.

PR-I0 must inspect the actual `max_concurrent_batches`, executor behavior, and
future queue on the authoritative path. If multiple scheduler outputs can be in
flight and the wire contract cannot carry their identity without ambiguity,
that mode is unsupported. The analyzer may not reconstruct it by choosing the
nearest timestamp.

## 6. Semantic entities

### 6.1 `schedule_cycle`

A schedule cycle is one invocation of the approved scheduler decision
boundary. It contains:

```text
cycle_start
state_before
constraint evaluation and scheduling work
scheduler output
state_after
cycle_end
```

It answers what the scheduler observed and decided. It does not imply device
work.

Required logical identity: `schedule_cycle_id`.

Legacy `iteration_id` may be retained only as explicitly labelled compatibility
metadata. It is not the sole semantic identity.

### 6.2 `logical_batch`

A logical batch represents every approved runtime SchedulerOutput, including a
zero-token output that is still dispatched for control, completion, or cleanup
behavior.

Required logical identity: `logical_batch_id`.

Required kind:

```text
work
empty_control
```

For `empty_control`:

- `scheduled_token_count == 0`;
- the batch-to-execution relation is still recorded when dispatch occurs;
- `device_attribution_eligible == false` unless a later profile freezes a
  meaningful zero-work device interpretation;
- it is never silently dropped from relation or completeness audits.

This avoids a relation hole when the runtime dispatches an empty
SchedulerOutput.

### 6.3 `execution_step`

An execution step is the host-observable envelope that consumes one approved
logical batch:

```text
executor_dispatch_observed
        -> final_model_result_observed
```

`final_model_result_observed` must occur after all execution needed to produce
the corresponding final model output, including a separate sampling call when
the approved path performs sampling after an `execute_model` future returns.

The envelope is not automatically one model-forward invocation, one kernel,
one device task, or one exact active interval.

Required logical identity: `execution_step_id`.

### 6.4 Relations and cardinality

The runtime must explicitly emit or deterministically propagate:

```text
schedule_cycle -> logical_batch
logical_batch  -> execution_step
```

The exact-SHA call-site map freezes supported cardinalities. IDs must not hide
an assumption that all three entities are permanently equal.

For the initial formal profile, any non-1:1 path is supported only when the
identity is explicitly propagated through every in-flight future. Otherwise it
is unsupported.

## 7. Scheduler state semantics

Every cycle records pre/post state. At minimum:

```text
waiting_engine_request_count_before
running_engine_request_count_before
waiting_engine_request_count_after
running_engine_request_count_after
```

The count unit is `engine_request`, not the ambiguous phrase
`request_or_sequence`. This is valid for the supported `n=1` profile. A future
profile with an independent sequence/group unit must introduce a different
field and semantics.

PR-I0 must define whether skipped/deferred waiting containers are included and
the exact observation point for every count.

Transition counts such as admitted, resumed, preempted, or finished may be
recorded only after their pinned-runtime meaning is frozen. No generic state
conservation equation may interpret `finished_req_ids` as requests finished
inside the current schedule call unless the call-site audit proves that
meaning.

Hard SQL invariants require synthetic and runtime-derived counterexamples
before wire freeze.

## 8. Constraint evidence architecture

### 8.1 Evidence boundary

The runtime records gate-local observations and branch outcomes. It does not
emit a final `token_budget_binding=true/false` or
`active_sequence_cap_binding=true/false` mechanism conclusion.

The analyzer derives:

```text
BINDING
NON_BINDING
INDETERMINATE
```

### 8.2 Token-budget semantics

The complete wire contract must preserve semantically equivalent facts to:

```text
configured_batched_token_budget
effective_batched_token_budget
token_budget_gate_checked
candidate_tokens_at_budget_gate
token_budget_before_at_gate
granted_tokens_at_budget_gate
running_count_at_budget_gate
waiting_count_at_budget_gate
effective_cap_at_budget_gate
budget_gate_queue
budget_limit_mode
```

`budget_limit_mode` preserves:

```text
not_limited
clipped
stopped_no_chunk
```

### 8.3 Active-sequence-cap semantics

The wire contract must preserve semantically equivalent facts to:

```text
configured_active_sequence_cap
effective_active_sequence_cap
cap_gate_checked
cap_gate_waiting_count
token_budget_at_cap_gate
running_count_at_cap_gate
effective_cap_at_gate
```

### 8.4 Multiple evaluations and bounded representation

A cycle can evaluate one constraint multiple times and can observe competing
constraints. A single mutually exclusive cycle-level stop reason is
insufficient.

PR-I0 must determine the maximum gate-evaluation cardinality. The subsequent
wire contract must choose and freeze one bounded representation:

1. lossless per-evaluation observations with a fixed maximum and explicit
   `constraint_observation_id` and `gate_ordinal`; or
2. a lossless-for-approved-aggregate-queries fixed-size summary whose mode and
   gate-state bucket counts account for every evaluation, plus deterministic
   raw witnesses defined before data collection.

In either representation:

- evaluated, encoded/accounted, and unclassified counts must balance;
- every omitted or truncated evaluation invalidates the cycle for binding
  evidence;
- no historical-request-sized container is permitted;
- the representation must distinguish gate-not-evaluated from missing
  evidence;
- multiple gates in one cycle must remain visible;
- capacity and observer-overhead proofs use the maximum encoded form.

### 8.5 Derived binding and legacy compatibility

For a complete token-budget observation set:

```text
BINDING       if any approved evaluation is clipped or stopped_no_chunk
NON_BINDING   if at least one evaluation occurred and every evaluation is
              not_limited
INDETERMINATE otherwise
```

The final wire contract must also freeze how active-cap evidence and competing
constraints qualify or confound this status.

The experiment repository's event-v3 `cap_binding` and `budget_binding`
booleans are legacy outputs, not fields to copy into the new runtime stream.
If compatibility is required, TraceLoom or the experiment adapter produces a
versioned compatibility view from the approved tri-state derivation and
records any information loss. `INDETERMINATE` must never be coerced to false.

## 9. Logical-batch composition

Every `work` logical batch exposes:

```text
scheduled_token_count
scheduled_engine_request_count
prefill_token_count
decode_token_count
```

Required invariant:

```text
scheduled_token_count == prefill_token_count + decode_token_count
```

The pinned-runtime call-site map must freeze the exact formulas. At minimum:

- prefix-cache hits are not counted as newly scheduled compute tokens merely
  because they are prompt tokens;
- chunked prefill records the scheduled chunk, not full prompt length;
- a mixed batch reports numeric prefill and decode totals;
- speculative decoding remains unsupported;
- `scheduled_engine_request_count` is the number of entries in the approved
  SchedulerOutput request-to-scheduled-token mapping for the supported `n=1`
  profile.

Optional KV usage should use an integer unit such as
`kv_cache_usage_basis_points` rather than an unbounded/NaN-capable hot-path
float.

## 10. Request identity and optional membership

When scheduler data links to lifecycle data, it uses or explicitly maps to the
canonical engine `lifecycle_id`.

A compact scheduler request key may exist only if it is:

- scoped by run, process, engine instance, and key generation;
- never reused within that scope;
- explicitly mapped to canonical `lifecycle_id` before formal request joins;
- privacy reviewed and bounded.

Full request-to-batch or request-to-step membership is not required for
aggregate v1. Aggregate queueing and client latency windows are aligned through
run identity and calibrated time. This permits aggregate service-side
attribution but does not permit per-request admission claims.

A future membership-enabled profile must record token contribution sufficient
for conservation and must pass its own capacity and overhead gates.

## 11. Clock architecture

Define:

```text
m = runtime CLOCK_MONOTONIC
h = caller CLOCK_REALTIME
p = msprof profiler-host clock
d = device TASK clock
```

The scheduler profile adds a bracketed bridge `q: m -> h`. Existing approved
TraceLoom clock components provide the relevant realtime/profiler/device legs.
Scheduler-to-device attribution composes only the applicable components; it
must not reuse a complete `p -> h -> d` epsilon as though it were the
scheduler's `m -> h -> d` uncertainty.

Scheduler-local durations remain direct monotonic differences:

```text
schedule_duration_ns = cycle_end_m - cycle_start_m
host_execution_envelope_ns = final_result_m - dispatch_m
```

Bridge samples contain at least the semantics:

```text
monotonic_before_ns
realtime_ns
monotonic_after_ns
sample_sequence
```

They are collected periodically outside the scheduler cycle, not once per
cycle. Runtime records carry host boot/clock-domain identity and bridge sample
scope. The analyzer, not the runtime, creates `clock_model_segment_id` after
deterministic discontinuity detection.

Before wire freeze, separate calibration data must determine and owner review
must ratify:

- minimum samples per segment;
- cadence and maximum sample gap;
- interpolation and any bounded extrapolation limits;
- fit/holdout rule;
- residual and drift thresholds;
- realtime-jump/segment-split threshold;
- uncertainty composition rule.

Acceptance values must be frozen before formal acceptance/mechanism data are
examined.

## 12. Scheduler-to-profiler join architecture

### 12.1 Join target

An execution step joins to a `profiler_execution_anchor`, not to each raw
kernel or device task.

A profiler execution anchor is one analyzer-normalized, profiler-visible host
execution range constructed from an approved anchor source and scoped by run,
executor process/context, rank/device, and time. Its child device tasks remain
attribution rows inside that anchor; their multiplicity does not make the step
join ambiguous.

The anchor can live in a worker/executor process different from the EngineCore
process that observed dispatch. PR-I0 must identify the approved
EngineCore-to-executor route and whether it carries an explicit handoff ID. A
manifest-declared single worker/rank may scope calibrated correlation, but it
does not create exact identity.

An execution anchor is not eligible for correlation until the scheduler-side
`executor_target_process_uuid` resolves through an approved
`runtime_profiler_process_binding` to the profiler-visible host process and
context. The binding receipt must preserve semantically equivalent facts to:

```text
runtime_profiler_process_binding_id
experiment_run_uuid
executor_target_process_uuid
runtime_pid
runtime_pid_namespace_identity
runtime_process_start_identity
executor_role
rank_id
device_id
profiler_visible_pid
profiler_context_identity
binding_source
binding_status
```

`binding_status` is exactly one of `exact`, `ambiguous`, `unmatched`, or
`unsupported`; only `exact` can scope an admitted execution-step join. This
process-binding status is independent of the execution-step join status.

PID alone is insufficient because it can be reused after process restart.
`runtime_process_start_identity` must distinguish process invocations, for
example with host boot identity plus procfs process-start ticks. The exact
receipt fields and acquisition authority are frozen after PR-I0; they need not
all be scheduler hot-path wire fields.

Calibrated correlation requires an approved runtime-process to
profiler-process/context binding. Rank, device, and time overlap alone do not
create process identity. A missing binding produces `unmatched`, multiple
admissible bindings produce `ambiguous`, and a mode with no approved observable
binding is `unsupported` in both the binding and attempted-join diagnostics.
An exact process binding scopes the candidate set; it does not upgrade a
temporal step join to `exact_identity`.

PR-I0/PR-I5 must name and validate the anchor source. If no supported anchor can
be constructed uniquely, the execution step is unmatched or unsupported.

### 12.2 Join statuses

Every attempted join resolves to exactly one:

```text
exact_identity
calibrated_correlated
ambiguous
unmatched
unsupported
```

Every result retains:

```text
join_status
join_relation
anchor_source
selected_profiler_execution_anchor_id  # nullable
candidate_count
runtime_profiler_process_binding_id
process_binding_status
clock_model_id
clock_uncertainty_ns
```

Every attempted join also materializes a bounded
`scheduler_profiler_join_candidates` relation with one row for every
admissible candidate anchor, keyed by the join-result ID and
`profiler_execution_anchor_id`. `candidate_count` MUST equal the number of
those rows. `selected_profiler_execution_anchor_id` is nonnull only for
`exact_identity` or `calibrated_correlated`, where it names the sole candidate.
It is null for `ambiguous`, `unmatched`, and `unsupported`. In particular, an
ambiguous result preserves all candidate IDs and never chooses a representative
anchor. PR-C1 must freeze the maximum candidates per attempted join and the
overflow behavior; overflow is evidence-fail-closed, not truncation.

`exact_identity` requires an explicit profiler-visible step-ID handoff and
validated uniqueness inside one approved runtime-profiler process binding.
Time overlap can never produce exact identity.

`calibrated_correlated` requires:

- a valid clock model covering the whole envelope;
- an approved robust containment/overlap rule under endpoint uncertainty;
- matching run and one approved executor-target-to-profiler process/context
  binding, rank/device, and supported-mode scope;
- exactly one admissible profiler execution anchor;
- no competing anchor under the same rule.

Nearest-timestamp selection is forbidden.

### 12.3 Initial evidence admission decision

For aggregate v1, both `exact_identity` and `calibrated_correlated` are eligible
for diagnostic mechanism evidence on the single-device supported profile.

`calibrated_correlated` must remain labelled correlation and cannot support a
per-request dependency or causality claim. Exact-only admission requires a
future explicit identity-anchor implementation; it is not a hidden prerequisite
for aggregate v1.

Before formal collection, owner review must freeze:

- the robust temporal predicate;
- minimum eligible-step and execution-duration join coverage;
- maximum ambiguous and unmatched fractions;
- deterministic tail-cohort/window construction and coverage thresholds;
- treatment of zero-token/control batches.

A run cannot promote only convenient matched steps while silently excluding
the tail or overloaded window.

### 12.4 Join-coverage population and denominator

Coverage is computed from scheduler evidence before profiler matching. For a
declared window `W`, the manifest first fixes `W` in the scheduler host-time
coordinate without using profiler match outcomes. Define `D_step(W)` as the
set of complete execution steps that:

- belong to the declared run, engine, runtime profile, and supported mode;
- consume a `work` logical batch with `device_attribution_eligible == true`;
- have a valid positive monotonic execution envelope; and
- have a non-empty intersection with `W`.

Each execution step occurs once in `D_step(W)`, even when it intersects
multiple request intervals. Missing process bindings, invalid or absent
scheduler-to-profiler clock models, profiler collection gaps, and missing or
ambiguous anchors do not remove an otherwise eligible step from the
denominator; they prevent that step from entering the admitted-join numerator.
Semantic exclusions and their reason codes are reported, and other hard gates
still reject malformed or incomplete scheduler evidence.

Let `J_step(W)` be the subset of `D_step(W)` whose join status is an admitted
`exact_identity` or `calibrated_correlated` result. Coverage has two distinct
units:

```text
step_join_coverage(W)
  = count(J_step(W)) / count(D_step(W))

execution_duration_join_coverage(W)
  = measure(union(step_envelope intersect W for step in J_step(W)))
    / measure(union(step_envelope intersect W for step in D_step(W)))
```

The duration calculation uses overlap-safe half-open interval unions. These
ratios must be reported separately and must never be averaged or relabelled as
request coverage. A zero denominator is `UNDEFINED`, not 100%, and cannot pass
a formal coverage gate.

Overall coverage uses the manifest-declared main analysis window. Tail
coverage uses a request-derived window constructed without request-to-step
membership:

1. Select the tail cohort from complete, eligible base-lifecycle requests in
   the predeclared analysis population, using the manifest-frozen TTFT metric,
   quantile or threshold, and deterministic tie rule.
2. For every selected request, construct a pre-first-token attribution
   interval from the approved lifecycle queue-entry boundary to its
   first-token boundary, then map it into the scheduler host-time coordinate
   through the approved lifecycle-to-scheduler clock/process relation. This is
   deliberately not the canonical Queue phase: the frozen Queue phase ends at
   `admission_started`, while this wider interval also contains Admission and
   Prefill. It is used only to define the TTFT-tail analysis window and must
   not be reported as queue duration or queue coverage.
3. Define `W_tail` as the half-open union of those intervals, intersected only
   with the predeclared main analysis window and the declared run/engine scope.
   It MUST NOT be clipped to profiler availability, successful joins, or
   convenient scheduler activity.
4. Evaluate both coverage ratios above using `W_tail`.

PR-C1 must freeze the exact lifecycle eligibility rule, TTFT source and
population, tail threshold/quantile, tie handling, interval endpoints, scope,
the lifecycle-to-scheduler mapping and boundary-overlap rule, and numeric
coverage thresholds. Failure to construct `W_tail` makes tail coverage
`UNDEFINED` and fails formal promotion; it cannot shrink the cohort or
denominator. Aggregate v1 does not claim that an individual tail request's
pre-first-token attribution interval is covered by a particular step;
per-request-window coverage requires the future membership-enabled profile.

## 13. Profiler interval attribution and conservation

The scheduler profile reuses the existing idle-evidence contract and its
terms, including:

- `productive_active`;
- `visible_productive_idle`;
- `blocked_by_visible_wait`;
- `capture_control_present`;
- `runtime_control_present`;
- `queued_visible_task_delay`;
- `host_sync_api_present`;
- `no_observed_device_work`;
- `unattributed_visible_idle`.

It does not define `device_idle`. Every interval is half-open `[start_ns,
end_ns)` and retains raw profiler provenance.

Clock-boundary uncertainty is a top-level mask, not an idle explanation. For
every promoted execution envelope:

```text
execution_window_ns
  = clock_boundary_uncertain_union_ns
  + classifiable_window_ns

classifiable_window_ns
  = productive_active_union_ns
  + visible_productive_idle_union_ns

visible_productive_idle_union_ns
  = blocked_by_visible_wait_union_ns
  + capture_control_present_union_ns
  + runtime_control_present_union_ns
  + queued_visible_task_delay_union_ns
  + host_sync_api_present_union_ns
  + no_observed_device_work_union_ns
  + unattributed_visible_idle_union_ns
```

All sums are over mutually exclusive, overlap-safe unions under the existing
category priority. There is no separate `other_explained_union_ns` beside
`visible_productive_idle_union_ns`.

An interval outside complete profiler collection is invalid for formal
promotion rather than silently relabelled. Negative duration, overlap double
counting, or either conservation failure invalidates the envelope.

## 14. Normalized analyzer model

TraceLoom must materialize tables or semantically equivalent IR for:

```text
scheduler_profile_runs
scheduler_cycles
scheduler_constraint_observations_or_summaries
logical_batches
execution_steps
cycle_batch_links
batch_execution_links
scheduler_clock_bridge_samples
scheduler_clock_models
runtime_profiler_process_bindings
profiler_execution_anchors
scheduler_profiler_joins
scheduler_profiler_join_candidates
scheduler_interval_attribution
scheduler_loss_intervals
scheduler_join_diagnostics
scheduler_tail_windows
scheduler_join_coverage
scheduler_audit_summary
```

Formal rows carry the applicable explicit scope:

```text
experiment_run_uuid
traceloom_run_id
process_uuid
profile_stream
engine_instance_id
scheduler_process_uuid
executor_target_process_uuid
runtime_profiler_process_binding_id
process_binding_status
device_id
rank_id
runtime_profile_id
scheduler_profile_config_id
schema_version
validity_status
```

Normalized tables and raw provenance are authoritative. Convenience views are
derived and never replace them.

## 15. Exporter and boundedness architecture

### 15.1 Disabled behavior

Scheduler profiling is default-off. When disabled it creates no scheduler
shard, queue, writer activity, record construction, or scheduler-specific clock
sampling and does not change scheduler decisions or request output.

### 15.2 Hot-path behavior

When enabled, the hot path performs bounded in-memory work only. It does not:

- open or flush files;
- synchronously wait for disk;
- call msprof;
- perform per-cycle clock calibration syscalls;
- allocate history-sized containers;
- use an unbounded per-request membership list.

### 15.3 One-shard capacity proof

The initial profile uses exactly one scheduler shard and sequence per
`process_uuid`. Rotation/segmentation is outside v1.

After PR-I0, the wire contract must prove separately:

1. peak producer records/bytes per cycle;
2. peak cycle rate;
3. maximum approved writer scheduling/service gap;
4. required queue records and bytes under that burst;
5. reserved-control demand during failures and close;
6. total run artifact bound from maximum cycles/duration and record size;
7. disk-space preflight and close/drain limits.

The total number of run records is not the in-memory queue capacity. Queue
capacity is a producer/consumer burst bound; total output is a separately
bounded single-shard artifact.

If the approved bounds cannot cover a formal run, the run is unsupported.
Overflow remains serving fail-open and evidence fail-closed.

## 16. Loss, completeness, and roster

Zero written loss intervals is not sufficient. A scheduler shard is complete
only with:

- valid start control record;
- valid final summary;
- balanced attempted/written/dropped accounting;
- valid content digest;
- drained close outcome;
- zero unexplained data-sequence gaps;
- zero writer and serialization failures over the entire shard;
- zero data drops and zero loss intervals over the entire shard;
- zero dropped control records;
- matching schema/config/runtime identities;
- committed shard receipt.

Claim-window filtering never relaxes shard completeness. Accounted loss
outside a selected analysis or tail window still invalidates the whole
scheduler shard, exactly as required by the unchanged frozen P0 completeness
rule.

A missing summary, writer crash, digest mismatch, missing shard, or missing
receipt fails closed even when no loss record was persisted.

The experiment manifest predeclares logical process/profile roles before run
admission. A post-launch receipt maps those roles to actual process UUIDs and
paths. Globbing observed shards cannot define the expected roster.

Formal aggregate attribution requires:

```text
all expected lifecycle shards complete
AND all expected scheduler shards complete
AND every required lifecycle/scheduler pair resolves to one process identity
AND every join-bearing executor target resolves through one approved
    runtime-profiler process/context binding
AND the pinned vLLM-0.21 base-lifecycle adapter receipt is valid
```

Missing relations, constraints, clock evidence, or profiler anchors are
reported as missing/ambiguous/unsupported and never repaired by timestamp or
nearest-neighbor inference.

## 17. Validation gates

### V0 — Runtime authority and call-site map

PASS requires the complete PR-I0 artifact described in Section 3, including
source-file and patch-set identity, analyzer-run-identity authority,
runtime-profiler process-binding authority, and a supported-mode matrix.

### V1 — Shard-overlay and disabled compatibility

Tests must prove:

- unchanged lifecycle wire bytes and legacy path;
- unchanged KV-recovery wire bytes and profile path when that optional stream
  is enabled;
- one shard/sequence per `(process_uuid, profile_stream)`;
- shared process UUID across enabled streams;
- independent ledgers, summaries, digests, and receipts;
- duplicate or cross-stream shards rejected;
- no scheduler work or artifact when disabled.

### V2 — Wire schema and protocol

After PR-I0, tests cover deterministic encoding, exact schema rejection, ID
scope, invalid relations, field bounds, privacy, malformed records, zero-token
batches, supported cardinalities, and multiple constraint evaluations.

### V3 — Exporter failures

Inject serialization failure, queue overflow, writer failure, close timeout,
missing summary, missing expected pair, digest mismatch, and dropped control
records. Serving remains fail-open; formal evidence fails closed.

### V4 — Semantic golden fixtures

Fixtures include:

- normal work cycle/output/execution;
- zero-token `empty_control` output with dispatch/result;
- multiple competing constraint gates;
- budget `not_limited`, `clipped`, and `stopped_no_chunk`;
- gate not evaluated versus evidence missing;
- incomplete gate-accounting rejection;
- invalid state invariant without repair;
- unsupported concurrent mode.

### V5 — Clock bridge

Fixtures cover offset, drift, bracket uncertainty, insufficient samples,
excessive gap, realtime discontinuity, cross-segment joins, invalid residual,
and composed uncertainty. Numerical values come from the separately frozen
clock-parameter table.

### V6 — Join and coverage

Fixtures prove:

- explicit ID handoff is required for exact identity;
- exact process scope requires an approved runtime process-to-profiler
  PID/context binding with process-start identity;
- PID reuse after restart, multiple workers, a missing binding, and multiple
  admissible contexts fail closed as specified;
- rank/device/time agreement without a process binding never admits a join;
- robust unique temporal relation produces only calibrated correlation;
- raw child-task multiplicity does not create anchor ambiguity;
- two admissible execution anchors produce ambiguity;
- every ambiguous join preserves all candidate anchor IDs in the bounded
  candidate relation and leaves the selected anchor null;
- nearest timestamps are never selected;
- invalid clock models promote no join;
- overall and tail windows preserve their pre-join denominators;
- tail windows are derived deterministically from request-level lifecycle
  evidence without claiming request-to-step membership;
- step-count and overlap-safe execution-duration coverage remain distinct;
- zero denominators are `UNDEFINED`; and
- overall and tail coverage gates fail closed.

### V7 — Two-level duration conservation

Every promoted fixture passes both top-level active/idle conservation and the
idle-explanation subpartition. All associated hard audit counters are zero.

### V8 — Real NPU positive path

A clean low-load run on the authoritative 910B2 profile demonstrates:

```text
runtime scheduler observation
-> paired lifecycle/scheduler shards and receipts
-> monotonic clock bridge
-> TraceLoom ingestion
-> runtime-profiler process/context binding
-> execution-anchor join classification
-> overall/tail coverage materialization
-> interval attribution
-> SQL audit
-> reproducible materialization
```

This is an integration gate, not mechanism proof.

### V9 — Deterministic real-envelope audit

A seed/rule and count/strata are frozen before results. The sample inspects raw
scheduler evidence, relation propagation, clock mapping, profiler anchor and
rows, and derived attribution. Manual post-result selection is forbidden.

### V10 — Observer overhead

Two contrasts are required:

1. scheduler incremental overhead: lifecycle, clock markers, msprof, workload,
   runtime, and device held constant; only scheduler profiling toggled;
2. whole formal evidence stack: baseline observation stack off versus the
   complete lifecycle+scheduler+clock+msprof stack on.

Client-side throughput, TTFT, and ITL measurements are common to both arms and
must not depend on the scheduler trace being enabled. Scheduler record-build
cost is measured by an independently available common timer or CPU
microbenchmark, not by comparing a trace-only metric that is absent in the off
arm.

Margins, confidence/equivalence method, repeat/power rule, randomization order,
and correctness criteria are frozen before examining acceptance data. A smoke
run is not an equivalence result.

### V11 — Fresh-clone reconstruction

From a fresh clone and immutable raw/retrievable inputs, reconstruct and audit:

- scheduler IR;
- clock model;
- runtime-profiler process/context bindings;
- profiler execution anchors and joins;
- request-derived tail windows and coverage reports;
- interval attribution;
- completeness and SQL reports;
- observer-overhead reports.

All source, schema, profile, rules, and artifact hashes must match.

## 18. Hard audit roster

At minimum, formal evidence requires zero:

```text
scheduler_id_errors
stream_shard_scope_errors
lifecycle_scheduler_pair_errors
cycle_batch_relation_errors
batch_execution_relation_errors
constraint_accounting_errors
constraint_coverage_errors
scheduler_clock_errors
cross_segment_join_errors
runtime_profiler_process_binding_errors
scheduler_profiler_join_errors
join_coverage_denominator_errors
join_coverage_errors
tail_join_coverage_errors
scheduler_loss_promotion_errors
scheduler_shard_completeness_errors
base_lifecycle_conformance_errors
duration_conservation_errors
idle_subpartition_errors
```

## 19. Formal evidence-promotion predicate

A run or declared analysis window is eligible only if all applicable terms are
true:

```text
architecture and multi-stream overlay approved
AND complete scheduler wire schema/config approved
AND exact runtime/adapter identity approved
AND pinned vLLM-0.21 base-lifecycle conformance receipt valid
AND all expected lifecycle shards complete
AND all expected scheduler shards complete
AND every additional predeclared enabled profile shard complete
AND lifecycle/scheduler process-profile roster paired exactly
AND balanced summaries, valid digests, and zero unaccounted loss
AND cycle -> logical-batch -> execution relations valid
AND all constraint evaluations completely accounted
AND clock model valid for the full promoted interval
AND no cross-segment join
AND every admitted join uses one exact and approved runtime-profiler
    process/context binding
AND join status is exact_identity or admitted calibrated_correlated
AND overall and tail step-count join coverage PASS
AND overall and tail execution-duration join coverage PASS
AND both duration-conservation levels PASS
AND all hard SQL counters are zero
AND destination scheduler-incremental overhead PASS
AND destination whole-stack overhead PASS
AND fresh-clone reconstruction PASS
```

Full request membership is not required for aggregate v1. The predicate admits
measurement evidence; it does not prove a mechanism hypothesis.

## 20. Formal artifact roster

Retain or reference with immutable hashes:

- experiment run manifest and run-ID mapping;
- predeclared logical process/profile roster and launch binding receipt;
- authoritative platform/profile receipt;
- core, device-plugin, scheduler-file, and adapter patch identities;
- base lifecycle conformance receipt, shard manifest, shards, and receipts;
- scheduler profile config, shards, and receipts;
- monotonic/realtime bridge observations and clock report;
- raw/retrievable msprof databases and collection-completeness report;
- runtime-to-profiler process/context binding receipts and audit report;
- analyzer and taxonomy/rules provenance;
- profiler execution-anchor and scheduler-join report;
- join coverage report with the pre-join overall/tail populations, request-
  derived tail-window definition, and separate step-count/duration units;
- interval attribution tables and two-level conservation audit;
- SQL audit and fresh-clone reconstruction manifest.

Observer-overhead evidence additionally retains assignment/order, both arm
manifests, predeclared margins/method, common client metrics, pair-level
results, and the aggregate decision report.

## 21. Materialized output surface

TraceLoom should expose a derived view such as
`v_scheduler_execution_evidence` containing at least:

```text
experiment_run_uuid
traceloom_run_id
runtime_profile_id
scheduler_profile_config_id
process_uuid
engine_instance_id
scheduler_process_uuid
executor_target_process_uuid
runtime_profiler_process_binding_id
process_binding_status
profiler_visible_pid
profiler_context_identity
device_id
rank_id

schedule_cycle_id
logical_batch_id
logical_batch_kind
execution_step_id
device_attribution_eligible

cycle_start_monotonic_ns
cycle_end_monotonic_ns
schedule_duration_ns

waiting_engine_request_count_before
running_engine_request_count_before
waiting_engine_request_count_after
running_engine_request_count_after

scheduled_token_count
scheduled_engine_request_count
prefill_token_count
decode_token_count

configured_batched_token_budget
effective_batched_token_budget
configured_active_sequence_cap
effective_active_sequence_cap
derived_budget_binding_status
derived_cap_binding_status
constraint_evidence_complete

execution_dispatch_monotonic_ns
final_model_result_monotonic_ns
host_execution_envelope_ns

selected_profiler_execution_anchor_id
candidate_count
join_status
join_relation
anchor_source
clock_model_id
clock_uncertainty_ns

productive_active_union_ns
visible_productive_idle_union_ns
clock_boundary_uncertain_union_ns
blocked_by_visible_wait_union_ns
capture_control_present_union_ns
runtime_control_present_union_ns
queued_visible_task_delay_union_ns
host_sync_api_present_union_ns
no_observed_device_work_union_ns
unattributed_visible_idle_union_ns

validity_status
```

Constraint observations/summaries and interval provenance remain normalized
source tables rather than being flattened away.

TraceLoom must also expose a coverage view such as
`v_scheduler_join_coverage` containing at least:

```text
experiment_run_uuid
engine_instance_id
coverage_window_kind
coverage_window_definition_id
tail_cohort_definition_id
eligible_step_count
admitted_join_step_count
ambiguous_step_count
unmatched_step_count
unsupported_step_count
step_join_coverage
eligible_execution_union_ns
admitted_execution_union_ns
execution_duration_join_coverage
coverage_status
```

`coverage_window_kind` distinguishes at least `overall` and `tail`. The tail
cohort/window definition retains its request metric source, population,
threshold or quantile, tie rule, lifecycle endpoints, and analysis-window
intersection. Denominator exclusions remain available by reason in normalized
diagnostics.

## 22. Approval and PR sequence

### PR-I0 — Runtime profile and call-site map

Repository: authority repository plus the selected runtime carrier.

Deliver the complete prerequisite in Section 3, including the analyzer run-ID
authority decision and runtime-to-profiler process/context binding design. No
hot-path implementation is authorized.

### PR-C1 — Complete wire and overlay approval candidate

Repository: parent protocol repository.

After PR-I0, deliver:

- exact `rlp.scheduler/v1alpha1` record schemas and encodings;
- exact ID and relation representation;
- exact constraint representation;
- exact limits and one-shard capacity proof;
- exact analyzer-derived run-ID derivation and versioned authority;
- exact alias or content-addressed bijection/migration binding to the cited
  idle-evidence v4.3 `run_id`;
- exact runtime-profiler process-binding receipt schema and authority;
- exact overall/tail coverage definitions and numeric thresholds;
- exact multi-stream overlay digest;
- schema/contract/runtime-profile/config digests;
- owner approval candidate and tests.

Only explicit owner approval of the exact digests authorizes implementation.

### PR-I1 — Parent exporter implementation

Implement record builders, multi-stream exporter integration, independent
ledgers/receipts, default-off behavior, and CPU failure tests against the
approved wire bytes.

### PR-I2 — Runtime adapter and hooks

Implement pinned cycle/state/constraint/output/execution observations,
relation propagation, and periodic bridge sampling in the repository selected
by PR-I0.

### PR-I3 — TraceLoom ingestion and IR

Implement scheduler ingestion, normalized tables, manifest/roster binding,
runtime-profiler process-binding ingestion, and completeness audits.

### PR-I4 — Monotonic clock bridge

Implement `m -> h`, deterministic segmentation, uncertainty composition, and
fixtures under the approved clock parameters.

### PR-I5 — Execution-anchor join and attribution

Implement profiler execution anchors, exact/correlated join classification,
process-binding validation, coverage gates, existing idle taxonomy reuse,
two-level interval conservation, and materialized views.

### PR-I6 — Profiler acceptance evidence

Deliver the real NPU positive path, deterministic audit sample, incremental and
whole-stack observer-overhead results, completeness receipts, and fresh-clone
reconstruction.

Formal queueing-mechanism experiments remain blocked until PR-I6 passes every
approved evidence-readiness gate.

## 23. Decisions still required before wire freeze

Architecture review may proceed now. The complete wire contract cannot freeze
until PR-I0 and explicit decisions resolve:

- exact record schemas, ID encodings, filename-safe stream identity, and
  maximum record size;
- analyzer-derived run-ID field set, canonicalization, digest encoding,
  authority path, and version;
- runtime adapter repository/patch carrier and exact source identities;
- supported execution cardinality, runtime-profiler process-binding source,
  and profiler execution-anchor source;
- per-evaluation versus sufficient-statistic constraint encoding;
- queue/byte/control/artifact/close limits for the one-shard design;
- clock sample, gap, fit, residual, drift, jump, and extrapolation values;
- robust join predicate, tail cohort/TTFT population, and numeric overall/tail
  step-count and execution-duration coverage thresholds;
- deterministic real-envelope audit strata/count/seed;
- incremental and whole-stack overhead margins, decision method, and power;
- vLLM-0.21 base-lifecycle adapter conformance and joint roster behavior.

These are evidence-architecture decisions. Token-budget experiments,
cardinality interventions, volatility metrics, `mu_eff`, mitigation, and paper
claims remain outside this contract.

## 24. Architecture review checklist

Reviewers should explicitly confirm:

- scope is aggregate queueing attribution;
- PR-I0 precedes the complete wire contract and implementation;
- `traceloom_run_id` is only a candidate analyzer-derived identity until its
  cited idle-evidence Draft v4.3 path/version/digest and exact JCS derivation
  are reverified by PR-I0 and frozen by PR-C1, or PR-C1 freezes an explicit
  content-addressed bijection/migration instead;
- the frozen P0 bytes are not silently edited;
- one shard/sequence per `(process_uuid, profile_stream)` is the intended
  overlay;
- repository ownership distinguishes core runtime from device plugin;
- current runtime identity includes file/patch state, not commit alone;
- zero-token SchedulerOutput remains represented;
- final execution completion includes sampling where applicable;
- state and cardinality count units are unambiguous;
- constraint evidence is multi-gate, complete, bounded, and analyzer-derived;
- event-v3 booleans are legacy compatibility outputs;
- full request membership is not required for aggregate v1;
- scheduler durations remain monotonic;
- analyzer owns post-hoc clock segmentation;
- profiler joins target execution anchors rather than raw child tasks;
- every admitted join has an approved runtime process-to-profiler PID/context
  binding;
- rank/device/time alone never establish process identity;
- calibrated correlation is admitted only with explicit labels and coverage;
- tail windows come from predeclared request-level lifecycle evidence, while
  step-count and execution-duration coverage keep distinct denominators;
- idle taxonomy is reused with two-level conservation;
- paired lifecycle/scheduler completeness is mandatory;
- both incremental and whole-stack observer overhead are tested;
- mechanism experiment and causal claims remain out of scope.

## 25. Proposed review wording

If the architecture is accepted, use wording equivalent to:

> Architecture approved for PR-I0. This approval accepts the aggregate scope,
> cycle/logical-batch/execution model, multi-profile shard overlay direction,
> raw constraint evidence boundary, clock composition, runtime-profiler
> process binding, execution-anchor join, request-derived tail windows,
> separate step-count/duration coverage, two-level duration conservation, and
> acceptance order. It does not freeze `rlp.scheduler/v1alpha1`, amend the
> owner-frozen P0 bytes, authorize hot-path implementation, or admit mechanism
> evidence. A complete wire-contract and overlay approval candidate must be
> submitted after PR-I0 with exact digests and all required evidence
> parameters.
