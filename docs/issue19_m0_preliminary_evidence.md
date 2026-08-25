# Issue #19 preliminary M0 evidence boundary

The original preliminary run is retained only in local custody under the
logical label `preliminary-normal-path-10`; its execution-node directory is
not part of the public evidence. Its ten service lifecycles
validly cover normal completion, client disconnect, timeout, duplicate abort,
natural KV recovery, exact terminal chains, clean observer shutdown, and
resource teardown.

Its aggregate `NO_GO` is not the formal Issue #19 M0 decision. The runner
waited for the first 63 requests to become quiescent and then used an
observer-drained Worker exit. It therefore did not prove that Worker death
overlapped an observable pending transfer. It also derived the zombie count
from the pre-Worker-exit quiescence snapshot, which cannot detect ownership
left by the final Worker-exit request.

The corrected M0 runner keeps the fixed model, data, request identities,
seeds, capacity, connector, and thresholds. It changes only the validity of
the preregistered failure observation:

- the verified Worker must durably witness a real submitted transfer that has
  not yet completed;
- the harness sends `SIGKILL` to that exact PID while the transfer is pending;
- final request and generation ownership are reconstructed from the surviving
  API/EngineCore terminal records and external process/resource state;
- only the killed Worker's exact trace/profile shard pair may be treated as
  externally closed; every other loss, malformed file, unclosed shard, unknown
  owner, live PID, or leaked mmap still fails closed.

The preliminary artifacts must not be deleted or rewritten, and their latency
distribution must not be presented as treatment or performance evidence.

## Pending-transfer run and subsequent oracle audit

The corrected ten-lifecycle diagnostic run is retained only in local custody
under the logical label `pending-sigkill-10`.
All ten repetitions independently witnessed the final
Worker-exit request's real `d2h_preserve` submission before `SIGKILL` reached
that exact owned Worker PID. In every repetition, the one submit without a
done record belonged to the killed Worker's process UUID. The service-level
shutdown removed the run-owned mmap and terminated the Worker and EngineCore.
Those are useful raw observations and remain immutable.

The later oracle audit found that the archived `NO_GO` summary is not a valid
formal decision. The old runner made resource pathology mutually exclusive
with the `correctness` term required for `GO`, inferred transfer invalidation
without a persisted ownership ledger, and reported fault-preceding survivor
latency without the preregistered paired normal boundary. All ten fault-state
snapshots contained zero generic resource observations. Consequently the raw
run is retained as `real-online` diagnostic evidence, while its formal status
is `INCONCLUSIVE_HARNESS_GAP`, not `NO_GO` and not M0 proof.

The repaired runner separates evidence validity from state conservation,
requires persisted capacity and transfer ownership, closes a killed Worker's
pending transfer only against the exact generation-exit event, verifies both
Worker and EngineCore termination, and fails closed while the paired latency
gate is absent. It does not alter the workload, capacity, seeds, or 8/10 and
10% thresholds. No lifecycle reconciliation treatment may be implemented or
enabled until a corrected M0 run provides valid evidence and reaches the
unchanged gate.

Before that run, the Issue preregistration must be clarified in public on two
points without changing its numeric gates. First, baseline evidence validity
(complete client, terminal, injection, observer, and ownership records) must
be distinguished from state conservation: an observed zombie or orphan is the
candidate baseline pathology, not missing evidence, while treatment
correctness still requires zero zombies and orphans. Second, the paired normal
boundary for the 10% survivor-p99 alternative must be defined before collecting
new results. The current worker-exit-last design terminates the service and its
reported survivor latencies precede that boundary, so they cannot evaluate the
latency alternative. Until those semantics are fixed, the runner reports the
latency gate as unavailable rather than silently choosing a comparison or
returning `NO_GO`.

## Corrected paired M0 result

The corrected paired run is published through the sanitized directory
`.benchmarks/results/m0_issue19_public/20260822-sanitized-corrected-paired-10/`;
its execution-node source remains only in local custody.
It contains ten fault arms and ten matched normal-control arms using the same
profiler, runtime, Ascend plugin, model, NPU, OASST1 projection, request order,
seeds, capacity, and resolved server configuration. Lifecycle reconciliation
remained disabled.

All ten pairs are real-online, evidence-valid, observer-complete, loss-free,
latency-evaluable, and process-clean. Every fault arm records the exact owned
Worker `SIGKILL` after a real pending-transfer witness. Transfer settlement by
that Worker generation's death is reported as external invalidation; it is not
misrepresented as an explicit connector `resource_invalidated` trace event.

Resource pathology occurred in one of ten repetitions. That repetition left
one orphan resource and one run-owned 8-GiB mmap; the other nine repetitions
had no zombie, orphan, or mmap residual. Matched latency pathology occurred in
zero of ten repetitions. Fault-arm survivor-p99 had a median of 95.9678 seconds
and an IQR of 2.6505 seconds.

Both observations are below the preregistered eight-of-ten gate, so the formal
decision for this specialty target is `NO_GO`. The complete evidence rules out
`INVALID_EVIDENCE`, while the observed one-off conservation failure prevents a
claim of universal baseline correctness. This result does not justify
implementing or enabling lifecycle reconciliation, changing the fixed workload
or thresholds, or generalizing the negative result beyond the tested
worker-exit-last generation-shutdown scenario.

The review-facing evidence is published only through the deterministic
sanitized export described in `docs/issue19_public_evidence.md`. Execution-node
logs and topology snapshots remain in local custody and are not public PR
artifacts.
