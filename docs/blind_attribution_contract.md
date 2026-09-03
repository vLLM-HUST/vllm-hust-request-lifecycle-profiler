# Blind attribution contract

Status: PR under review. No opaque case has been revealed and no new
event type, scorer rule, or paper claim may be justified by this document until
the contract review has concluded.

This contract implements the research convergence requested in Issue #19 and
the mainline evaluation requested in Issue #1. It is an ordinary experimental
protocol, not an approval, co-signature, hash-freeze, or attestation system.

## Center claim

Request Lifecycle normalizes events across frontend, scheduler, KV, executor,
and response components into an identity-preserving and completeness-checked
lifecycle DAG. Under matched control/intervention evidence, it should produce
more reliable and actionable mechanism rankings than the same normalized
evidence viewed as aggregate metrics, flat timers, or timed raw-log/manual
diagnosis, and it should abstain when the evidence does not support a single
mechanism.

The study tests this claim; it does not assume it is true. The project remains
`NOT_M0_PROVEN` until the opaque evaluation and reveal are complete.

## Non-goals

- Do not infer that the longest phase is the causal root cause.
- Do not infer that a complete trace is causal proof. Completeness establishes
  only that the evidence is eligible for analysis.
- Do not implement a generic execution tree, profiler-row model, or timeline
  visualization that duplicates TraceLoom.
- Do not treat a TraceLoom span or raw profiler row as a request-level causal
  edge without an explicit request, lifecycle, epoch, batch, or handoff link.
- Do not implement the Issue #19 reconciliation treatment or reinterpret its
  fixed `NO_GO` as a new optimization attempt.
- Do not claim runtime speedup, broad low overhead, population-level diagnosis
  accuracy, or benchmark #95 performance evidence from this three-case pilot.
- Do not use historical public cases or synthetic fixtures in blind accuracy.
  They remain development and scorer-regression inputs only.

## TraceLoom interface boundary

TraceLoom is the source of timeline-native structured execution evidence. The
repository pins `third_party/traceloom` at
`63e86fc5095ee2552400c8a6c2c863faeaabf0b4`. At that commit the preferred
interface is its self-contained augmented SQLite output rather than parsing
the human-readable Loop Tree. The older candidate
`1931cc7a4711cb371a1d510636e07f247016d2d9` predates this database contract and
must not be used for the study.

Request Lifecycle may consume these existing TraceLoom relations:

- `traceloom_event` for typed intervals and stable event keys;
- `traceloom_event_source` for source table/row lineage;
- `traceloom_anchor` for ordered semantic anchors;
- `traceloom_semantic_tree`, `traceloom_semantic_node`, and
  `traceloom_semantic_edge` for recovered tree/rank structure;
- `traceloom_viz_node_anchor` and `traceloom_tree_node_occurrence` for exact
  occurrence membership and overlap-safe cost packets;
- `traceloom_runtime_call`, `traceloom_device_work`,
  `traceloom_runtime_device_relation`, and `traceloom_v_sync_runtime_call` for
  typed host/device and synchronization support; and
- `traceloom_cuda_graph_replay` and `traceloom_cuda_graph_envelope` when graph
  evidence is available.

The Request Lifecycle adapter adds links, not a second tree representation. A
link row must contain:

- `trace_id`, `engine_lifecycle_id`, `recovery_epoch`, and request identity;
- batch/step identity when one device occurrence serves multiple requests;
- TraceLoom `tree_id`, `node_id`, `occurrence_idx`, `anchor_id`, and/or
  `event_id` as applicable;
- link kind (`request_handoff`, `batch_membership`, `execution_support`, or
  `resource_owner`);
- owner and clock domain;
- evidence source and support state; and
- a reason for any missing or ambiguous join.

An interval overlap is not sufficient proof of membership. If request-to-batch
membership, cross-clock alignment, or handoff identity is unavailable, the
adapter records residual evidence and the diagnosis must abstain rather than
guess an edge.

Every device-backed candidate must be drillable through the explicit chain
`request/lifecycle edge -> TraceLoom tree node occurrence -> anchor/event ->
source table and source key`. The profiler stores only the join keys and
support state; TraceLoom remains the owner of the tree and raw-row lineage.

## Opaque case matrix

The minimum matrix contains exactly three fresh cases for the first pilot:

| Case class | Count | Required oracle |
| --- | ---: | --- |
| Positive, one actionable mechanism | 2 | One independently controlled mechanism and a rank-one intervention that can reverse or materially reduce it. |
| Valid insufficient evidence or no single root cause | 1 | Evidence is complete, but either the effect is below the frozen floor or no mechanism reaches the frozen dominance threshold. |

Case IDs must be semantically neutral. The diagnosis side must not see fault
manifests, case labels, salts, intervention assignments, or the oracle until
all pre-reveal outputs are locked. Historical artifacts already visible to the
diagnosis side cannot be reused as cases.

The custody side (Team A) prepares the three case bundles and ground-truth
reveal. The diagnosis side (Team B) receives only the normalized evidence
package and a fixed time budget. Each case bundle contains at least five
independent matched baseline/intervention service-lifecycle pairs in alternating
AB/BA order. Role separation is required for a genuine blind result; it is not
a request for project-wide co-signing or approval.

Before reveal, each method must write an immutable ordinary result artifact
containing:

- top-1 and top-3 candidates;
- confidence and candidate share;
- unexplained residual;
- abstain decision and reason;
- the proposed rank-one counterfactual when not abstaining;
- start/end time and time-to-localize; and
- input completeness and loss status.

The diagnosis budget is 30 minutes per method per case, measured from the first
access to the case bundle until the result artifact is closed. Automated arms
also report their actual wall-clock runtime and may finish early. Environment
setup and case-bundle validation happen before the timed interval and must be
identical across arms. A non-opaque development case must first confirm that a
human can complete the raw-log/manual workflow within 30 minutes; this
calibration cannot contribute to blind accuracy.

Rules, thresholds, candidate vocabulary, and parsers may not change after a
case is inspected. Post-reveal improvements apply only to future cases and
cannot be rescored as blind success on these three.

## Fair comparison arms

Every arm receives the same case requests, same normalized source events, same
clock model, same completeness report, and same diagnosis time budget. No arm
may receive an answer-bearing label that the others do not receive.

1. Aggregate TTFT, TPOT, latency, throughput, and error metrics.
2. Flat stage timers with no request-scoped causal or ownership edges.
3. Raw normalized event rows and logs with timed manual diagnosis.
4. Lifecycle spans with causal ranking rules disabled.
5. Full request-scoped lifecycle DAG with matched diff, identity/ownership
   edges, confidence, residual, and abstention.

The shared case bundle is the source of truth. Each arm is a deterministic view
or presentation of that bundle. Direct fault names, injected-pressure labels,
or oracle-only markers are excluded from all diagnosis inputs. Every arm must
rank or abstain using the same candidate vocabulary; the machine-readable
source of truth is `docs/blind_attribution_candidate_vocabulary.json`:

- `frontend_tokenization`;
- `queue_or_admission`;
- `scheduler_dispatch`;
- `worker_handoff`;
- `kv_allocation_or_capacity`;
- `graph_or_batch_transition`;
- `device_prefill`;
- `decode_execution`;
- `communication_or_synchronization`;
- `response_streaming`;
- `cleanup_or_resource_release`; and
- `insufficient_evidence_or_multi_cause`.

## Coarse-prefill decomposition

The current `scheduled -> prefill_done` interval is localization only. The
next schema must represent the following non-exclusive substages without
duplicating TraceLoom's device execution tree:

| Substage | Minimum boundaries and owner | Evidence source |
| --- | --- | --- |
| Scheduler selection/dispatch | selection start/end, dispatch emit; scheduler owner | vLLM scheduler lifecycle events |
| Worker handoff | dispatch, worker receipt, execution start; scheduler and Worker owners | explicit transport/roster handoff |
| KV allocation/free-block | allocation start/end/result, requested/allocated blocks, free-block state | scheduler/KV-manager events and resource ownership ledger |
| Graph/batch transition | batch membership, graph key lookup, hit/miss, capture/replay, shape transition | runtime batch metadata plus TraceLoom graph evidence where supported |
| Device prefill | device prefill start/end for a concrete batch occurrence | TraceLoom typed interval and raw-row lineage joined by explicit batch/step identity |
| Communication/synchronization | typed communication/synchronization start/end and supported runtime/device relation | TraceLoom typed support plus explicit rank/request/batch membership; never timestamp overlap alone |
| Completion handoff | Worker completion and EngineCore receipt | explicit Worker-to-core handoff |

Each span requires owner, clock domain, start/end, evidence source, and explicit
request-to-batch membership. Overlapping spans remain DAG nodes and are not
globally sorted into invented causality. Missing fields increase residual and
may force abstention.

## Pre-blind scorer and noise calibration

The current evaluator defaults of `5.0 ms` and `0.60` predate the opaque cases.
The dominance rule is retained, but the absolute `5.0 ms` value is only a
lower bound: it is not assumed to exceed real-service jitter.

Before Team B receives an opaque case, run five independent no-intervention
matched pairs on the exact target in alternating AB/BA order. Using only those
declared non-opaque calibration pairs, define:

- `null_delta_p95_ms`: the nearest-rank 95th percentile of the absolute total
  positive matched delta (therefore the maximum for five calibration pairs);
- insufficient-evidence floor:
  `max(5.0 ms, null_delta_p95_ms)`;
- single-root dominance: top-1 positive-delta share `>= 0.60`;
- no-single-root-cause abstention: top-1 share `< 0.60`;
- unexplained residual share for a non-abstained result: `<= 0.40`; and
- incomplete identity, event loss, clock ambiguity, unmatched configuration,
  or a top-candidate paired 95% bootstrap interval that includes zero: fail
  closed and abstain.

The calibration command, five pair results, computed floor, scorer
configuration, and fixed bootstrap seed `2026082701` must be committed before
opaque case access. They may not be recomputed after reveal. For every case,
report all five paired deltas, median/IQR, the 95% paired bootstrap interval,
and top-1 selection frequency across 10,000 lifecycle-pair resamples.

The reported `dominance_score` is the top-1 positive-delta share. The reported
`confidence_score` is the smaller of dominance score and bootstrap top-1
selection frequency. Unexplained residual share is `1 - dominance_score`.
These are predeclared pilot scores, not calibrated population probabilities.
Baseline methods report the same fields where meaningful; three cases cannot
estimate a reliable population calibration curve.

The candidate list is derived from explicit lifecycle and ownership evidence,
not only elapsed time. Workload size, prompt/output token counts, concurrency,
and batch shape must be matched or normalized before ranking. Overlapping
spans use critical-path/union accounting rather than double charging.

The three-case pilot supports the center claim only if all of these hold:

1. the full DAG is non-abstained and top-1 correct on both positive cases;
2. it correctly abstains on the negative case;
3. both non-abstained top-1 candidates pass their rank-one counterfactual;
4. the full DAG obtains a strictly higher three-case decision score than the
   strongest non-DAG arm, where one point is awarded for each correct positive
   top-1 and for the correct negative abstention; and
5. there is no correctness failure, information leak, unmatched input, or
   post-reveal rule change.

If the strongest baseline ties the full DAG at 3/3, the pilot does not support
an independent diagnostic-advantage claim, even if the DAG is correct. Report
the tie rather than changing cases or thresholds.

## Counterfactual gate

For every non-abstained top-1, change only the predicted mechanism. Use the
same commits, requests/order, hardware, and resolved configuration. Across at
least five alternating matched service lifecycles per arm, the
counterfactual passes only when:

- correctness remains 100% for unaffected requests and the case-specific
  oracle;
- the target matched delta decreases by at least 30% in the paired median;
- the direction is consistent in at least four of five pairs and its paired
  95% bootstrap interval excludes zero;
- no non-target primary service metric regresses by more than 3% in paired
  median; and
- observer evidence is complete and loss-free.

A failed counterfactual makes the corresponding top-1 attribution incorrect
for the decision-impact claim, regardless of whether its phase was longest.

## Reported metrics

Report every case and every method, not only successful rows:

- top-1 and top-3 accuracy;
- mean reciprocal rank;
- attribution precision, false positives, and false negatives;
- abstention precision and coverage;
- unexplained residual in time and share;
- wrong-attribution severity: `0=correct/correct-abstain`, `1=wrong adjacent
  stage`, `2=wrong optimization family`, `3=unsafe or correctness-risking
  action`, using the adjacency/family rubric in the candidate-vocabulary file;
- time-to-localize under the fixed budget; and
- counterfactual success rate.

Observer overhead is a separate P1 claim. Pair trace off/on for short-request,
long-context, decode-heavy, and high-concurrency workloads, with at least three
independent service lifecycles per side in alternating order. Report every
repetition plus median/IQR for TTFT, TPOT/TBT, P95/P99 latency, throughput,
error rate, CPU, host RSS, NPU HBM, trace bytes/request, exporter loss, and
exporter timeout. A broad low-overhead claim additionally requires median TTFT,
TPOT, and throughput changes within 3%, P99 change within 5%, zero new errors,
and zero trace loss. Otherwise report the measured boundary without weakening
the threshold.

## Stop and downgrade conditions

Stop or downgrade the independent causal-diagnosis claim when any of the
following occurs:

- the blind matrix does not outperform the strongest flat/non-DAG baseline;
- a non-abstained top-1 fails its counterfactual;
- coarse prefill cannot be narrowed to an actionable mechanism;
- request identity cannot be joined across process, rank, transport, and
  TraceLoom evidence;
- correct answers depend on visible fault markers;
- reasonable abstention leaves too little valid coverage;
- observer overhead exceeds the stated boundary; or
- TraceLoom plus minimal request metadata fully supplies the claimed
  independent contribution.

If causal superiority fails, retain the protocol, exporter, and request-link
adapter as shared observability artifacts. Do not relabel a failed causal claim
as a performance result.

## Candidate dependency pins and cost

The contract draft was prepared against these exact source states:

- profiler/Issue #19 durable-boundary head:
  `fc8fb2bd67153df9b09cc414c9352e7f6a103649`;
- vLLM-HUST runtime:
  `c180d643c66f7a12434ae551cfc83cd7b7795302`;
- vLLM-Ascend-HUST:
  `95f390bb7816b5d557eb327c110b801f2a5b2cf5`;
- llm-serving-workloads:
  `76e24c85bcab76ecfabb831c9444002b6efffd58`;
- OASST1:
  `fdf72ae0827c1cda404aff25b6603abec9e3399b`;
- TraceLoom:
  `63e86fc5095ee2552400c8a6c2c863faeaabf0b4`;
- Qwen/Qwen2.5-14B-Instruct model revision:
  `cf98f3b3bbb457ad9e2bb7baf9a0125b6b88caa8`.

Before case construction, the final profiler contract commit, TraceLoom
dependency path, model revision, target device class/count, workload rows and
order, service configuration, case-custody location, and time budget must be
recorded in the repository. TraceLoom should be pinned as a repository
dependency rather than consumed from an unrecorded ambient checkout.

The initial candidate target is one Ascend 910B2 with the model revision above.
Estimated cost is 2--3 person-days for the adapter, scorer, calibration, and CPU
fixtures; 10--16 NPU-hours for calibration, three-case matched capture, and
five-pair counterfactuals; 4--6 additional NPU-hours for the four-workload
overhead matrix; and about one person-day for locked scoring, reveal, and
reporting. These are planning estimates, not measured results.

## Required artifacts

- contract and candidate-vocabulary file committed before case access;
- normalized case bundle schema and deterministic five-arm renderer;
- scorer tests using development fixtures only;
- per-method locked pre-reveal outputs and timing records;
- custody-side reveal and case-validity record;
- rank-one counterfactual manifests and raw outputs;
- complete score table, errors, residuals, abstentions, and overhead rows; and
- a claim-ledger update that reports success, tie, failure, or downgrade
  without deleting Issue #19's negative result.
