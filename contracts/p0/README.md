# M0 Minimum Runtime Protocol Freeze

- Status: `owner_frozen`
- Evidence status: `NOT_M0_PROVEN`

This directory is the minimal repository-owned preparatory subset for M0 causal
phase attribution. It turns the first host-side planning step derived from
[issue #1](https://github.com/intellistream/vllm-request-lifecycle-profiler-plugin/issues/1)
and its inherited requirements into a content-addressed P0 decision: define the phase
DAG, inventory already exposed development cases, specify the minimum runtime
API, and record the repository/evidence boundary before changing runtime code.

The minimum runtime contract and phase taxonomy are owner-approved by exact
SHA-256 in `owner-freeze-approval.json`. This approval is not a scored blind
result, an M0 proof, or a performance claim. The historical NPU6 artifacts
were already exposed to the diagnostician and therefore remain development
fixtures only.

## Frozen contents

- repository-root `AGENTS.md`: durable mission, ownership, runtime, evidence,
  environment, and merge-gate instructions for later agents;
- `p0-manifest.json`: exact source links, repository pins, target policy,
  validation state, and remaining gates.
- `owner-freeze-approval.json`: machine-readable owner decision, approved
  content digests, P1 base pair, and communication-mode restriction.
- `runtime/phase-taxonomy.v0-draft.md`: streaming-aware phase DAG and boundary
  definitions for queue, admission, prefill, decode, communication,
  serialization, delivery, and cleanup.
- `runtime/minimum-runtime-contract.v0-draft.md`: concrete P1 proposal for
  identities, clocks, terminal/cleanup semantics, bounded exporter parameters,
  loss accounting, privacy, and supported modes.
- `evaluation/development-cases/development-case-table.md`: human-readable
  inventory of checked-in historical artifacts and their allowed uses.
- `evaluation/development-cases/development-case-inventory.json`:
  machine-readable declaration that those cases are ineligible for primary
  blind metrics.

The larger workspace-local staging pack named
`request-lifecycle-profiler-p0` contains extended runtime/experiment review
drafts and blind-custody record templates. Those files are intentionally not
copied here yet: they require executable schemas, validators, and owner
decisions, and are not prerequisites for beginning local P1 development.

## Verified baseline

The authenticated recursive checkout was verified on 2026-08-02:

- parent: `84261a2458e1f961b0279b70780ca9497bad3f2e`;
- workloads gitlink: `76e24c85bcab76ecfabb831c9444002b6efffd58`;
- historical runtime-hook gitlink: `0daab7a300fb91efebd35b221b9a6f6c6d7486f8`;
- audited current runtime main: `f229ba7cad21a4dba58681af6738a9fd947388e2`;
- current device-plugin main:
  `cafad89a5e103f31ea517c1edb56130578c3cd56` (its only change from the
  previously audited `590855422...` snapshot is CI setup-python metadata);
- current benchmark main: `0858cdb326e88ebaf8027966ba754da5ea800db4`;
  its registry bytes remain version `1.0.0` with SHA-256
  `2073283467797cbe4a74682249b4e40c7c5ded4ebd393392161e038dd9bdb94c`.

The parent and both submodules were clean at the pinned commits before this
candidate branch was created. No runtime source was changed and no NPU run was
launched.

## Owner freeze record

On 2026-08-02, Remygred accepted all eight minimum API decisions below:

1. Exact phase names and boundaries, especially admission, communication,
   serialization, delivery, and cleanup.
2. Whether `stream_done` moves to the HTTP/SSE send boundary and which
   component owns the new root `request_done` terminal.
3. Identity topology and per-record schemas for root request, engine sample,
   response, span, event, explicit edge, loss interval, chunk, and preemption
   epoch.
4. Terminal precedence, executable supported-mode path grammar, and
   lifecycle/trace/shard completeness rules.
5. Monotonic clock representation and cross-process correlation rule.
6. Bounded, non-blocking exporter capacity, overflow/drop accounting, flush
   timeout, process-shard trailer, and fail-open behavior.
7. Cleanup component roster and all bounded enums/field-size/privacy limits.
8. The current-runtime/device-plugin compatibility pair used as the P1 base.

The approved bytes are:

- minimum runtime contract SHA-256:
  `122963930919073179d4844422d21e85da3a522def3ace723eb992eac43cdade`;
- phase taxonomy SHA-256:
  `82aae94c5d124b846f77684e239714d51791115608e786079c4ea4bd4ca05abd`.

P1 is pinned to runtime
`f229ba7cad21a4dba58681af6738a9fd947388e2` and device plugin
`cafad89a5e103f31ea517c1edb56130578c3cd56`. Its communication profile is
restricted to `communication_mode=none`; any future `issue2:*` profile still
requires its own frozen dependency. The two approved Markdown files retain
their pre-approval titles and `freeze_candidate` text because those bytes are
part of the approved digests. Do not edit them in place: create a new version,
digest it, and obtain a new owner approval.

P1 may now begin locally and may open as a draft. The full Team A/B custody
protocol, fresh
two-positive/one-negative blind set, scoring thresholds, comparator budgets,
and reveal procedure must be frozen before a formal P2/P3 scored run. They do
not block local exporter development, but they do not waive the performance-PR
merge gate described below.

## Inherited research and merge gates

The migrated source `vllm-hust#185` names public retrospective candidates
`vllm-hust#163`, `vllm-hust#151`, and `vllm-ascend-hust#145`. Their identities
are now exposed to Team B, so reproduction owners/Team A may use them to create
development artifacts or rotate/redact inputs, while Remygred consumes opaque
traces and does not duplicate the underlying root-cause task.

The combined acceptance metrics are critical-path share, attribution
precision, time-to-localize, trace overhead, cross-run variance, top-1/top-3
accuracy, MRR, confidence, unexplained residual, abstention, and
wrong-attribution severity. Every non-abstained top prediction requires a
rank-one counterfactual.

Any performance implementation PR, whether official or specialty, remains
merge-blocked by the combined gate: benchmark #95 owns canonical artifact
admission, while the alternating-run and correctness rigor is inherited from
vllm-hust #185. The evidence needs matched base/head, at least three independent
service lifecycles per side in alternating order, raw request/runtime artifacts,
environment manifest, exact core/plugin pair, correctness gate, reported error
rate, target-specific acceptance threshold, every repetition, and median/IQR.
It must also record `metadata.data_source` starting with `real-online` (or an
explicitly allowlisted CI real-online source), target ID/version/profile/hash,
workload, resolved configuration, artifact-local
`leaderboard_manifest.json` and `run_leaderboard.json`, canonical paths/URLs,
and any deviation/specialty reason. A smoke, replay, derived summary,
skipped/cancelled job, or missing provenance fails closed.

## Formal evaluation decisions still open

- Freeze an exact graph-mode `specialty-target` spec for blind localization.
- Freeze an exact matched overhead target; the current active official target
  is eager-only and can serve only as provenance/reference evidence.
- Select at least two fresh opaque positive cases and one evidence-insufficient
  negative case under Team A custody.
- Freeze flat versus structured comparator inputs, top-k/confidence/residual
  outputs, top-1/top-3/MRR/time-to-localize/overhead/error-severity metrics,
  abstention scoring, and the rank-one counterfactual oracle.

## Validation boundary

This frozen package consists of Markdown and strict JSON records. The
prescribed conda environment
`vllm-request-lifecycle-profiler-exp` is not present in this container, so no
project Python test or benchmark was run while creating it. Do not substitute
an ad-hoc virtual environment. P1 CPU work remains blocked until that
environment is restored, and formal NPU6 work remains blocked by the separate
evaluation gates above.
