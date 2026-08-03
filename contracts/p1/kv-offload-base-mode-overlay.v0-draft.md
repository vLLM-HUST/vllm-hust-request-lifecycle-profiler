# Local KV-Offload Base-Mode Overlay v0 Draft

- Proposed overlay ID: `rlp.trace-mode/kv-offload-v1alpha1`
- Review status: `p0_owner_review_required`
- Activation status: `BLOCKED_BY_P0_OWNER_MAPPING_CONFIG_AND_IMPLEMENTATION_GATES`
- Evidence status: `NOT_M0_PROVEN`
- Runtime implementation status: `NOT_STARTED`

This is a minimal, content-addressable conformance overlay for the frozen
`rlp.trace/v1alpha1` contract. It does not edit either P0 file, approve the
issue-2 mapping, activate a non-`none` communication mode, authorize G1, admit
hardware, or establish a performance result.

## 1. Why an overlay is required

The frozen P0 grammar permits only
`kv_cache_mode=disabled|local_homogeneous`, requires no KVConnector in
`local_homogeneous`, and lists KVConnector-backed cache as diagnostic-only.
The owner-approved G0 implementation family instead uses runtime-core
`OffloadingConnector/TieringOffloadingSpec`. No truthful P0 root-mode value
currently describes that configuration.

The communication grammar also says that every operation required by a frozen
issue-2 profile has a paired base span with generic execution-child edges. The
proposed recovery mapping deliberately has a narrower base roster: only H2D
restore has a P0 pair; asynchronous D2H preservation and process-wide worker
wait remain closed profile-only facts. Its H2D bridge connects a just-closed
execution epoch through restore to the next admission rather than an
in-epoch compute child.

An issue-2 approval cannot change those P0 rules. This overlay is the separate
P0-owner decision needed to make the specialty mapping representable without
lying about the connector or manufacturing request-scoped D2H/wait edges.

## 2. Exact dependencies

| Dependency | Content identity | Required status before activation |
| --- | --- | --- |
| Minimum runtime contract | SHA-256 `122963930919073179d4844422d21e85da3a522def3ace723eb992eac43cdade` | owner-frozen and byte-immutable |
| Phase taxonomy | SHA-256 `82aae94c5d124b846f77684e239714d51791115608e786079c4ea4bd4ca05abd` | owner-frozen and byte-immutable |
| Recovery profile | `rlp.kv-recovery/v1alpha1`, SHA-256 `b363532884d1cae8049ab080d2b85a629f3b33a75f6621788d1e4c8f30737666` | profile-owner frozen |
| Recovery profile approval | SHA-256 `2831ce52802e7cbe4ec092431c71c18de05491da7ac8d48512014b1d43b3cb0c` | profile-only approval |
| Specialty mapping candidate | `issue2:kv-recovery-v1alpha1`, SHA-256 `dca914f989f3a98d43fb9fa2538f7c43a375e8f22f5deb7e09343aee5ee7bc19` | separate issue-2-authority approval required |
| Runtime | `vLLM-HUST/vllm-hust@f229ba7cad21a4dba58681af6738a9fd947388e2` | exact source pin |
| Device plugin | `vLLM-HUST/vllm-ascend-hust@cafad89a5e103f31ea517c1edb56130578c3cd56` | exact source pin |

The mapping row is a normative dependency, not an approval granted by this
document. If its bytes change, this overlay candidate must be reviewed against
the new digest.

The incomplete #134 configuration candidate at
`contracts/p1/benchmark-134-fixed-8gib-config-candidate.json` is a
non-normative design input only. Its changing review digest is deliberately
not embedded here, so refinement of that non-runnable artifact cannot create a
digest cycle with this overlay. It is not an exact dependency frozen by
overlay approval. Before activation, one later joint admission record must
bind this overlay's approved digest to a complete, separately approved
replacement configuration digest. Changing that final configuration then
requires a new joint admission record and overlay compatibility review, not a
claim that the incomplete candidate was approved.

## 3. One added root-mode value

When and only when every gate in this overlay is satisfied, the supported-mode
grammar gains this one value:

```text
kv_cache_mode=local_offload
```

It means exactly:

- one host, TP=1, PP=1, DP=1, `sampling_n=1`, `sample_index=0`, rank 0;
- decoder-only text generation on one Ascend 910B2 logical device;
- runtime-core `OffloadingConnector`, `kv_role=kv_both`;
- runtime-core `TieringOffloadingSpec`, no `kv_connector_module_path`, no
  `spec_module_path`, and no device-plugin NPU offloading spec;
- `secondary_tiers=[]` and a positive, authority-frozen
  `cpu_bytes_to_use` in a fully resolved configuration;
- `recompute_scheduler_enable=false`,
  `SLO_limits_for_dynamic_batch=-1`, and the default runtime scheduler class;
- base `communication_mode=issue2:kv-recovery-v1alpha1`; and
- the exact paired base/profile expected-process roster and receipts.

This overlay covers only #134's proposed `tiering_enabled` row using
`TieringOffloadingSpec`. It does not define or approve `tiering_disabled`.
The current non-executable proposal for that row uses `CPUOffloadingSpec`,
which is outside both the selected profile-owner implementation decision and
this overlay. It needs a separate profile-owner compatible-pair decision or a
new profile digest, plus a new/expanded P0 overlay digest, before it can become
a formal connector mode.

Any other connector, spec, topology, rank count, secondary tier, dynamic or
recompute scheduler override, missing resolved value, or changed source pin is
diagnostic-only under this overlay. `local_offload` must never be emitted for
HBM-only/no-connector control, CPUOffloadingSpec, RecomputeCPUOffloadConnector,
NPUOffloadingSpec, or NPUTieringOffloadingSpec.

The HBM-only control continues to use the original
`kv_cache_mode=local_homogeneous` plus `communication_mode=none` and has no
KVConnector. This overlay does not redefine that path.

## 4. Required root binding metadata

In addition to every original supported-root field, the root `received`
metadata for `local_offload` contains exactly these overlay bindings:

```text
kv_cache_mode_profile="rlp.trace-mode/kv-offload-v1alpha1"
kv_cache_mode_profile_sha256=<final SHA-256 of this overlay artifact>
kv_recovery_profile_sha256="b363532884d1cae8049ab080d2b85a629f3b33a75f6621788d1e4c8f30737666"
communication_mapping_sha256="dca914f989f3a98d43fb9fa2538f7c43a375e8f22f5deb7e09343aee5ee7bc19"
resolved_configuration_sha256=<approved complete configuration SHA-256>
```

Every `*_sha256` value is exactly 64 lowercase hexadecimal characters and must
equal the digest cited by its applicable explicit authority record. All keys
and values obey
the existing P0 scalar, ASCII, and 1024-byte metadata bounds. These fields bind
a run to approvals; they do not substitute for the
profile start record, run manifest, process receipts, or resolved parameters.
The current incomplete configuration-candidate digest is forbidden in the
`resolved_configuration_sha256` runtime field.

## 5. Closed base-operation exception

For this exact overlay/mapping pair, the phrase “every operation required by
that profile emits its paired span” applies to the mapping's closed
**base-operation roster**, not to every recovery-stream observation label:

| Recovery observation | P0 pair | P0 edges | Required treatment |
| --- | ---: | ---: | --- |
| `h2d_restore` | exactly 1 per accepted positive recovery episode | exactly 3 per pair | formal base operation after every gate passes |
| `d2h_preserve` | 0 | 0 | exact profile submit/done only; base emission forbidden |
| `transfer_wait` | 0 | 0 | exact process/run point-membership only; request fan-out forbidden |

This exception is exact, not an omission license. A valid run still captures
all applicable D2H and wait profile facts, loss accounting, close receipts,
and orphan/duplicate/failure rejection required by the approved profile and
mapping. Adding a D2H base span, a transfer-wait base span, or another active
issue-2 evidence code requires a new content-addressed mapping and overlay (or
a new base schema when a process-scoped interval topology is needed).

Within one engine lifecycle this overlay admits either zero or one accepted
positive recovery episode. Zero H2D pairs are permitted only when no positive
episode exists; this is an explicit exception to P0's default “absent only in
`communication_mode=none`” wording. Such a trace may be a complete supporting
request trace when all applicable profile-only D2H/wait and loss/receipt facts
are complete, but it is never positive recovery evidence. One episode requires
exactly one H2D pair and three edges. A second episode/pair in the same engine
lifecycle is unsupported by this overlay and requires a new version. A formal
state-machine benchmark run must contain at least one accepted positive
lifecycle even though other request lifecycles may have zero H2D pairs.

## 6. Recovery-bridge exception

For `issue2:kv-recovery-v1alpha1:h2d_restore`, the generic P0 communication
child wording is specialized to this exact three-edge recovery bridge:

```text
preempted(e)
  -> communication_started(e+1)
  -> communication_done(e+1)
  -> first admission_started(e+1) after successful scheduler_wakeup
```

The outer edges are `data_dependency` with the issue-2 code; the inner edge is
`program_order / instrumented_execution_context`. All event, identity,
metadata, timestamp, epoch, span, duplicate, graph, and endpoint rules in the
approved mapping remain mandatory. The internal edge additionally requires
the mapping's explicit bounded pending context keyed by `transfer_id`; same
process, poll order, or timestamps alone are insufficient. G1 must prove that
accepted submission stores the exact start/event/request/epoch/block context
and that the first matching raw completion atomically consumes it before the
done event and edge are emitted. This exception does not allow communication
to remain open across preemption: its start occurs only after the closing
`preempted(e)` and the span must finish before admission or another
preemption/terminal.

No timestamp-derived edge, D2H return edge, scheduler-wait span, or device-idle
claim is added by this overlay.

## 7. Combined conformance and failure behavior

A `local_offload` trace is formally eligible only when all of these exact
digests have explicit authority records: P0 contract/taxonomy, this overlay,
recovery profile, issue-2 mapping, and complete resolved configuration. A
separate final joint admission record must bind the exact overlay SHA-256 and
P0-owner overlay-approval-record SHA-256, issue-2 mapping SHA-256 and issue-2
approval-record SHA-256, complete resolved-configuration SHA-256 and
configuration-approval-record SHA-256, recovery-profile SHA-256 and profile-
owner-approval-record SHA-256, and the frozen P0 contract/taxonomy digests plus
their applicable approval records. That joint record must be co-signed by the
P0 owner and the #134 configuration authority and must cite the separate
issue-2-authority approval; neither signer may substitute for issue-2
authority, and the P0 owner's joint-record signature cannot substitute for the
separate frozen overlay-approval-record identity. Any byte change, approval-
record change, or digest mismatch invalidates the joint record and requires a
new one. The run
must also pass every unchanged P0 rule through an overlay-aware validator, the
overlay rules, the complete profile/mapping validators, expected-process
receipts, scheduler/interface gates, and collection/loss checks.

Any missing approval, digest mismatch, incomplete configuration, unsupported
mode, absent event/edge/profile fact, orphan transfer, loss, invalid metadata,
or process-roster mismatch rejects formal evidence. Serving remains fail-open;
evidence fails closed. The runtime must not fall back to
`local_homogeneous`, erase the connector, or report `communication_mode=none`
to make an invalid connector run appear supported.

An unsupported root uses only the frozen P0 reason enum, with this deterministic
precedence: cross-host uses `cross_host`; heterogeneous block layout uses
`heterogeneous_kv_cache`; an absent/unapproved/mismatched issue-2 mapping,
communication digest, or unsupported communication topology uses
`communication_subtype_unfrozen`; every other wrong connector, spec, source
pin, overlay/config digest, scheduler override, rank/topology value, or missing
resolved field uses `kv_connector_enabled`. No new reason string is minted.
If several conditions apply, the first reason in this precedence is emitted.
The optional bounded human-detail metadata may identify the local check but
never replaces `reason_code`.

The current `runtime_protocol.py` rejects non-`none` communication and does not
recognize `local_offload`. That behavior remains correct until G0 approvals are
complete. Implementing this overlay is later G1 work and is not authorized by
this draft.

## 8. Claim boundary

Overlay conformance proves only that the connector-enabled lifecycle can be
represented under approved trace grammar. It does not prove genuine pinned
imports, platform startup, device collection, idle attribution, copy overlap,
a complete recovery capture, speedup, a benchmark result, or M0.

## 9. Proposed P0-owner approval items

The P0 owner must accept or replace each item while citing this artifact's
final SHA-256:

1. overlay ID, exact dependency digests, and non-modification of frozen P0
   bytes;
2. the single new `kv_cache_mode=local_offload` meaning and exact supported
   topology/`tiering_enabled` implementation family, excluding the unresolved
   CPUOffloadingSpec `tiering_disabled` row;
3. the required root binding metadata and later joint overlay/complete-
   configuration admission-record rule;
4. the H2D-only paired base-operation roster, zero-or-one per-lifecycle
   cardinality exception, and closed zero mappings for D2H and transfer wait;
5. the exact cross-epoch H2D recovery-bridge interpretation;
6. unsupported-reason mapping plus preservation of all other P0 grammar,
   validation, loss, receipt, and fail-closed evidence rules;
7. independent issue-2 mapping, configuration, CPU/G1, and later hardware
   gates; and
8. content-addressed immutability and the prohibition on treating this
   approval as G1, NPU, service, experiment, performance, or M0 authority.

P0-owner approval of this overlay alone still cannot activate the mode. The
issue-2 mapping and complete configuration need their separate approvals, and
the approved runtime implementation does not exist yet.
