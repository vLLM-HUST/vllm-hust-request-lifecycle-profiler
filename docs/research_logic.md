# Seven-Step Research Logic

[Complete historical original](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/db79a80ae22f974e31d19fd84ba2a20ed919290c/archive/mod-targeted-20261023/profiler-entry-docs/snapshot/docs/research_logic.md).
[Evidence and consumer map](entry_evidence.md); historical observations are not current
readiness or performance qualification. Status remains `NOT_M0_PROVEN`.

## 1. Problem

How can an LLM serving system turn per-request lifecycle traces into causal
bottleneck attribution rather than a pile of correlated logs?

## 2. Importance

Optimizations often fail because the apparent bottleneck is not the causal
bottleneck. Aggregate TTFT/TPOT and scattered logs cannot reliably distinguish
queueing, prefill, KV pressure, decode jitter, streaming stalls, and cleanup
delays.

## 3. Existing Gap

Serving systems expose metrics and logs, but they rarely produce request-level
causal evidence packets that connect events across tokenizer, scheduler, KV
manager, executor, and streamer.

## 4. Key Idea

Represent each request as an ordered lifecycle trace and classify the dominant
bottleneck chain using explicit event spans and controlled fault-injection
ground truth.

The current implementation has two trace layers: client-observed proxy anchors
and internal runtime hook events. Claims must name the layer they use, then
show when internal spans confirm or overturn the client-visible hypothesis.

## 5. Feasibility

Historical capture and smoke-overhead observations are retained in the
benchmark original and [roadmap evidence map](entry_evidence.md). They do not
establish current runtime readiness or general bounded overhead. The remaining
question is matched blind attribution and counterfactual validation.

## 6. Evaluation

Baselines: raw logs, simple stage timers, manual diagnosis, and profiler with
causal rules disabled.

Metrics: attribution accuracy, false positives, false negatives, tracing
overhead, event coverage, memory overhead, TPOT/TTFT deltas, and
time-to-root-cause.

## 7. Takeaway

This work investigates whether request lifecycle traces can become auditable causal
evidence for LLM serving optimization. To become a top-tier systems paper, it
must show that this evidence changes the next optimization decision compared
with raw logs or aggregate timers.
