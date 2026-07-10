# Request Lifecycle Causal Profiler

## Research Question

Can request-level lifecycle traces be converted into causal bottleneck
attribution for LLM serving, so optimization work targets the true limiting
stage instead of correlated symptoms?

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
claim ledgers that other optimization repositories can cite.

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

Go if the profiler can correctly attribute controlled bottlenecks with low
overhead and generate paper-ready evidence packets. Stop or narrow if traces
cannot disambiguate bottlenecks beyond what simple stage timers already show.

