# E3 Stream Semantics Addendum — v0 Freeze Candidate

> **Historical, non-normative design note.** Approval, freeze, authority,
> attestation, digest-chain, and activation-gate language below is retained only
> to explain project history. Current policy is defined by `AGENTS.md`,
> `CONTRIBUTING.md`, `.github/BRANCH_POLICY.md`, the implementation, and tests.

- Contract ID: `rlp.idle-evidence/e3-stream-semantics-addendum/v0`
- Status: `freeze_candidate`; issue-2 authority approval required
- Evidence status: `NOT_M0_PROVEN`
- Scope: E3 per-stream observable-state interpretation after merged-shard
  import, E1 semantic classification, and E2 productive-timeline analysis
- Activation effect: none

This file is the independent, content-addressed addendum requested after the
Idle Evidence Contract v4.3 bytes were fixed. It freezes only the E3 semantics
that were decided during the subsequent review of
`vLLM-HUST/vllm-hust-perf-analyzer#15`. It does not edit, replace, or silently
extend the bytes identified as Idle Evidence Contract v4.3.

`MUST`, `MUST NOT`, `REQUIRED`, and `MAY` have RFC 2119 meanings.

## 1. Independent dependency boundary

Any consumer claiming conformance to these post-v4.3 E3 semantics MUST bind
both of the following immutable semantic dependencies by independent SHA-256:

1. Idle Evidence Contract v4.3:
   - repository: `intellistream/vllm-request-lifecycle-profiler-plugin`;
   - source commit: `7e10622eb5755e1af544546e93e3f63a91214ffc`;
   - path: `docs/idle_evidence_contract.md`;
   - version text: `Draft v4.3 (proposed for M0 approval)`;
   - SHA-256:
     `8edb42b706b6cab14dfde2b109841cb8af090883c9ea86696ee779de21d0c9ed`.
2. This addendum's exact raw bytes, including line endings, under an
   independently recorded SHA-256.

The addendum does not embed its own digest because that would be
self-referential. An approval record, mapping, resolved configuration, or run
manifest that depends on it MUST cite the external SHA-256 of these exact
bytes. Approval of v4.3 does not approve this addendum, and approval of this
addendum does not change the approval state of v4.3.

The v4.3 dependency remains authoritative for interval algebra, clock and
alignment rules, communication canonicalization, collection completeness,
evidence levels and relations, and its claim boundary. This addendum is
authoritative only for the E3 cases enumerated below. A conflict MUST fail
conformance closed and return to issue-2 change control; an implementation
MUST NOT resolve it by silently rewriting either dependency.

## 2. Engineering provenance, not semantic dependency

The checked-in engineering source for this addendum is merged
`vLLM-HUST/vllm-hust-perf-analyzer#15`:

- PR head: `4edd7639ef046de835df9ff10833d1e6f9cb45aa`;
- merge commit: `8093c226a981206107a13601172427706599b505`;
- per-device/unassigned-stream review commit:
  `819bd15ec571f4fe0d4fe92e4c7801cda1880b0d`;
- zero-duration point-marker commit:
  `88967c83751be48e3ec1e5d46d7b447306d18c89`; and
- final unassigned-stream semantics commit:
  `4edd7639ef046de835df9ff10833d1e6f9cb45aa`.

The following SHA-256 values identify the relevant files at both the PR head
and merge commit:

| Engineering file | SHA-256 |
| --- | --- |
| `native/include/traceloom/analysis/stream_state_timeline.h` | `118408e20d202843d5681643eb5c645c8f3ad0e084070ab4c47e62c41bdd01b8` |
| `native/src/analysis/stream_state_timeline.cpp` | `efbd1b46d36b85bb74ceac545cca696c6e36ea771fbf35110c540e61ae7f1ca3` |
| `native/tests/analysis/stream_state_timeline_tests.cpp` | `e1aa307e54b3b5e45c48d683623431b6bb9fbac655b37c0b0a6d1b7d4eb99878` |
| `notes/idle-evidence-audit.md` | `fb91943c01d315de83028a96eaeb226e247473c8998da339950fa3439fcb612a` |

These commits and file digests are audited implementation/conformance
baselines. They are not a third immutable semantic dependency. A later
implementation may use different source bytes without a new addendum only if
executable tests attest that every normative outcome below is preserved.

The audited PR #15 bytes are **not yet conformant** to one deliberately
fail-closed intersection in this addendum. They return from the legal
zero-duration point path before applying the unassigned-stream sentinel
downgrade, so a legal point carrying `0xFFFFFFFF` currently leaves scan
completeness unchanged. Sections 3, 5, and 7 instead require the two axes to be
evaluated independently: the row remains point-only and creates no interval or
universe membership, while the sentinel still makes the affected device
incomplete. This stricter intersection follows issue-2 authority comment
`5164544402`'s requirement that unassigned stream makes the corresponding
device incomplete; it is an explicit approval decision, not a behavior that
may be inferred from PR #15. Before activation, the implementation must change
and pass conformance case 4. Until then PR #15 is provenance and partial
engineering evidence only, not executable conformance to this addendum.

## 3. Terms and evaluation order

- `device scope` is one logical `(run_id, device_id)` after all discovered
  profile shards for that device have been merged.
- `duration` is `end_ns - start_ns` in the event's device clock domain.
- `unassigned-stream sentinel` is exactly the unsigned 32-bit value
  `0xFFFFFFFF` carried when the adapter observed an event but had no stream
  metadata and therefore appended no corresponding stream row.
- `legal point role` is one of `visible_wait`, `capture_control`, `record`, or
  `runtime_control` after the content-addressed semantic ruleset classifies a
  TASK row.
- `point-only observation` is a TASK row with a legal point role and
  `end_ns == start_ns`.
- `productive role` is `productive_compute`, `productive_comm`, or
  `productive_data_move`.
- `interval-bearing observation` has strictly positive duration and survives
  validation and stream resolution into a stream-state timeline.
- `observed stream universe` retains the v4.3 definition: for one device
  scope, it contains streams with at least one interval-bearing canonical
  event intersecting the analysis span. It is not the set of all runtime
  streams.

An E3 implementation MUST apply these decisions without allowing one axis to
erase another:

1. identify the affected device and apply the `0xFFFFFFFF` completeness rule
   in Section 5 independently of duration;
2. reject negative duration;
3. classify zero duration as either a legal point-only observation or invalid
   input according to Section 6;
4. do not perform interval or stream-universe construction for a legal
   point-only observation; and
5. construct an interval only for a remaining valid positive-duration
   observation with an assignable stream.

Consequently, a legal zero-duration point carrying `0xFFFFFFFF` remains
point-only and establishes no stream membership, while the independently
observed unassigned-stream condition still makes that device's scan incomplete.

## 4. Per-device universe and completeness

E3 MUST calculate the following fields first for each device scope:

- `stream_universe_size`: the number of emitted stream timelines for that
  device; and
- `observed_universe_scan_complete`: whether every observed interval-bearing
  event on that device was placeable into the declared observed universe.

Run-level values MUST then be derived as follows:

```text
run.stream_universe_size =
    sum(device.stream_universe_size for every device result)

run.observed_universe_scan_complete =
    AND(device.observed_universe_scan_complete for every device result)
    AND no device-unattributable input damage exists
```

The fields MUST NOT be calculated from one process shard and then copied to a
device or run. A healthy device MUST NOT inherit another device's sentinel or
input-damage flag. One incomplete device does, however, make the aggregated
run completeness false.

For an E2 device result with no claimable E3 analysis span, such as
`no_productive_span` or `invalid_analysis_span`, E3 emits no timeline and a
zero universe. Its scan-completeness flag MAY remain vacuously true, but the
non-`ok` analysis status still forbids an absence claim. Vacuous truth MUST NOT
be relabeled as observed completeness or device-idle evidence.

## 5. Unassigned-stream sentinel

For any event whose raw stream ID is exactly `0xFFFFFFFF`, E3 MUST:

1. retain the observation's source lineage and identify the affected device;
2. treat the stream identity as observable but unassignable, not as an
   invented stream and not, by the sentinel alone, as corrupt input;
3. emit the bounded diagnostic `unassigned_stream`;
4. emit no stream timeline for `0xFFFFFFFF`;
5. emit no interval for that event, including when its duration is zero;
6. add no member to the device's observed stream universe;
7. leave the run analysis status unchanged by the sentinel alone; and
8. set the corresponding device's
   `observed_universe_scan_complete=false`.

The run-level completeness aggregation in Section 4 therefore becomes false.
Other valid streams and timelines on the same device remain available as
positive observations, but they cannot repair the affected device's absence
attestation. If the same row is a legal zero-duration point, both the point-only
rules in Section 6.1 and this completeness consequence apply.

`0xFFFFFFFF` is a distinguished adapter sentinel, not a wildcard and not a
real stream ID. A positive-duration event whose unresolved stream ID is any
other value follows the existing damaged/unknown-stream path: it is invalid
input, emits no fabricated timeline, and makes the affected device scan
incomplete.

## 6. Zero-duration observations

### 6.1 Legal point-only observations

A zero-duration TASK row is legal only when its semantic role is one of:

- `visible_wait`;
- `capture_control`;
- `record`; or
- `runtime_control`.

E3 MUST treat such a row as a profiler point marker. It MUST:

- preserve source lineage in the diagnostic path;
- emit `zero_duration_point_event_ignored`;
- emit no zero-length interval;
- add no interval boundary to another event's timeline;
- establish no interval-bearing stream-universe membership;
- leave device and run analysis status unchanged by the point alone; and
- leave `observed_universe_scan_complete` unchanged by the point alone, while
  preserving any independent sentinel or damaged-stream downgrade.

If the same stream is already a universe member because of another valid,
positive-duration event, the point does not remove that membership; it simply
does not create or enlarge membership itself. If the point is the only
observation associated with a stream, that stream MUST NOT appear in the
interval-bearing observed universe.

A positive-duration observation with one of these roles remains
interval-bearing under v4.3 and may produce `running_wait`,
`running_capture_control`, `running_record`, or `running_runtime_control`.
The point exception MUST NOT erase a real positive interval.

### 6.2 Invalid zero or negative duration

A zero-duration observation is invalid input when it has any productive role
or the `unknown` role. A zero-duration canonical `COMMUNICATION_OP` is also
invalid because it represents productive communication rather than one of the
four TASK point roles. E3 MUST emit no interval, report
`invalid_event_duration`, degrade the run to `invalid_input`, and set the
affected device's `observed_universe_scan_complete=false`.

A negative-duration observation is invalid for every role. It has the same
invalid-input and incomplete-scan consequences and MUST never be normalized
into a point or have its endpoints reordered.

## 7. Normative outcome matrix

The following table records the minimum externally observable behavior. “No
status change” and “unchanged” mean that the row itself does not degrade an
otherwise healthy result; another damaged row may still do so.

| Input observation | Diagnostic | Analysis status effect | Interval or timeline from this observation | Universe membership from this observation | Device scan completeness effect |
| --- | --- | --- | --- | --- | --- |
| Positive duration, stream `0xFFFFFFFF` | `unassigned_stream` | No status change | None; no sentinel timeline | None | Set false |
| Zero duration, legal point role, assignable stream | `zero_duration_point_event_ignored` | No status change | None | None | Unchanged |
| Zero duration, legal point role, stream `0xFFFFFFFF` | `zero_duration_point_event_ignored` plus unassigned-stream lineage | No status change | None | None | Set false |
| Zero duration, productive role | `invalid_event_duration` | `invalid_input` | None | None | Set false |
| Zero duration, `unknown` | `invalid_event_duration` | `invalid_input` | None | None | Set false |
| Zero duration, canonical communication op | `invalid_event_duration` | `invalid_input` | None | None | Set false |
| Negative duration, any role | `invalid_event_duration` | `invalid_input` | None | None | Set false |
| Positive duration, unresolved non-sentinel stream | `unknown_stream_identity` | `invalid_input` | None | None | Set false |

No row in this table authorizes E3 to fabricate an interval or repair a
missing stream association from timestamp adjacency, source order, another
device, a request ID, or a nearby stage.

## 8. Claim boundary

This addendum preserves and narrows the v4.3 claim boundary:

- `observed_universe_scan_complete=true` is necessary but not sufficient for
  `complete_absence_observation` or `no_observed_device_work`. The v4.3
  collection-status, shard-import, table-readability, drop/truncation,
  interval, and evidence-relation gates still apply.
- `observed_universe_scan_complete=false` for one device forbids an absence
  claim for that device. Because run completeness is an AND, it also forbids
  a run-level claim that depends on complete observed-universe coverage.
- An unassigned event does not prove work on a particular stream, but its
  inability to be placed means absence cannot be established for the affected
  device.
- A point-only observation proves only that the profiler reported a point
  marker. It supplies no positive duration, no zero-length coverage, no
  interval-universe membership, and no evidence that a wait or control action
  caused, covered, or consumed an idle gap.
- Ignoring a legal point marker is not event loss and does not by itself void
  scan completeness. It also MUST NOT be counted as productive duration,
  visible-idle duration, explanation coverage, or a performance metric.
- Invalid productive/unknown zero-duration input cannot be downgraded to a
  harmless point to recover a complete run.
- Neither a complete scan nor any timeline produced under this addendum proves
  true hardware idle, dependency causality, a runtime bottleneck, a regression,
  or a performance improvement. The strongest eligible absence wording
  remains v4.3's “no profiler-visible device work was observed,” and only when
  all v4.3 gates pass.

This addendum does not define a KV-recovery operation roster, H2D/D2H or wait
mapping, runtime edge endpoint, cross-process handoff, P0 base-mode overlay,
resolved experiment configuration, or joint admission. It does not approve
`issue2:kv-recovery-v1alpha1`, enable a non-`none` communication mode, unlock
G1, admit NPU execution, authorize a service or experiment, support a
performance claim, or establish M0.

## 9. Minimum executable conformance cases

An implementation claiming this addendum MUST execute deterministic tests for
at least all of the following:

1. a positive-duration `0xFFFFFFFF` event beside a healthy real stream: run
   status remains `ok`, the diagnostic is present, no sentinel timeline is
   emitted, the healthy timeline remains, and device/run completeness is
   false;
2. two devices with a sentinel on only one: device universe sizes are local,
   only the affected device is incomplete, the run universe is their sum, and
   run completeness is false;
3. a zero-duration example for each of the four legal point roles on assignable
   streams: the diagnostic is present, no interval is emitted, a point-only
   stream does not enter the universe, and completeness remains unchanged;
4. a legal point with stream `0xFFFFFFFF`: no interval/universe member is
   emitted and the affected device/run completeness is false;
5. a valid positive-duration event on the same stream as a legal point: the
   positive event alone establishes membership and the point adds no interval;
6. zero-duration `productive_compute`, `productive_comm`,
   `productive_data_move`, `unknown`, and canonical communication-op examples:
   each is invalid input and voids device/run completeness;
7. a negative-duration example: endpoints are not reordered and the result is
   invalid input;
8. an unresolved non-sentinel stream: no timeline is fabricated and the
   affected device is incomplete; and
9. a non-`ok` E2 device: no E3 universe or absence claim is manufactured from
   a vacuously true scan flag.

The test result MUST bind the addendum SHA-256, v4.3 SHA-256, semantic-ruleset
version and SHA-256, implementation commit, and exact input fixtures. Passing
synthetic or checked-in conformance fixtures proves contract behavior only; it
MUST NOT be presented as runtime-matched A/B, online performance evidence, or
M0 proof.

## 10. Change control

Any change to the sentinel identity, duration-role partition, diagnostic
outcome, per-device aggregation, interval/universe membership, completeness
effect, or claim boundary requires:

1. a new addendum version at a new path;
2. a new SHA-256;
3. updated executable conformance fixtures; and
4. explicit issue-2-authority approval.

Implementation refactoring does not require a new semantic version when it
preserves every outcome and passes the content-bound conformance cases.
Approval of this freeze candidate, if granted, applies only to its exact
external SHA-256 and has no activation effect beyond making it an immutable
semantic dependency for later mappings and admission records.
