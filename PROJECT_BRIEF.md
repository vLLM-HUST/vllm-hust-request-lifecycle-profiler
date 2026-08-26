# Request Lifecycle Causal Profiler

## Research Question

Can an identity-preserving request lifecycle DAG, under matched
control/intervention evidence, produce more reliable and actionable mechanism
rankings than equal-budget aggregate metrics, flat timers, and raw-log/manual
diagnosis, while abstaining when the evidence is insufficient?

## Why This Is Worth Doing

The course material repeatedly uses the request lifecycle as the minimum
observation unit: tokenizer, queueing, prefill, decode, KV allocation, streaming,
and cleanup. Existing logs often expose these events separately but do not
connect them into a replayable cause chain. This project turns lifecycle
observability into a reusable research artifact.

## Core Mechanism

Collect a per-request event timeline and infer bottleneck chains such as:

- tokenizer or validation delay;
- queue pressure before prefill;
- prefill compute saturation;
- KV allocation or prefix-cache pressure;
- decode iteration jitter;
- slow streaming client backpressure;
- teardown or cleanup stalls.

The profiler should produce both human-readable reports and machine-readable
claim ledgers that other optimization repositories can cite. A longest stage
is localization and a complete trace is evidence validity; neither alone is a
causal root cause. Every non-abstained top-1 requires matched evidence and a
rank-one counterfactual.

TraceLoom owns the generic execution tree, occurrence-preserving timeline cost,
and raw profiler-row lineage. Request Lifecycle consumes that structured
evidence and adds request/lifecycle/epoch identity, resource ownership,
matched-intervention ranking, confidence/residual, abstention, and decision
gates. It must not duplicate TraceLoom's tree or row representation.

## Initial NPU Binding

- Reserved device: NPU6
- Project conda env: `vllm-request-lifecycle-profiler-exp`
- Shared baseline env may be cloned from `vllm-hust-dev`; do not install project
  overlays into the shared baseline.

## Evidence Plan

Use `llm-serving-workloads` for normal, long-context, RAG-like, and bursty
workloads. Add repo-local injected-fault workloads for controlled causal tests.

Minimum first experiments:

1. Trace schema and synthetic unit tests.
2. Existing-server probe on one NPU that records lifecycle events without
   changing behavior.
3. Controlled fault-injection runs: long prompt surge, decode-heavy batch, slow
   streaming client, and KV pressure.

Primary metrics:

- attribution accuracy under injected faults;
- time-to-root-cause compared with raw logs;
- false positive and false negative attribution rate;
- overhead of tracing;
- coverage of lifecycle events.

## Stop/Go Standard

The Issue #19 worker-exit-last reconciliation hypothesis is a scoped `NO_GO`;
do not rerun or retune it. The topic-level causal claim advances only if two
fresh opaque positives and one valid negative show a strict decision-score
advantage over the strongest non-DAG baseline and every non-abstained top-1
passes its counterfactual. Stop or downgrade the independent causal claim if
the DAG ties/fails the baseline, cannot narrow coarse spans, depends on answer
markers, or imposes unacceptable observer overhead.
