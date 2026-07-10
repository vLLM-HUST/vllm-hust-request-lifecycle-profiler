# Seven-Step Research Logic

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

## 5. Feasibility

The first implementation can run as no-op instrumentation on NPU6. It does not
need to change scheduling policy until attribution accuracy and overhead are
measured.

## 6. Evaluation

Baselines: raw logs, simple stage timers, manual diagnosis, and profiler with
causal rules disabled.

Metrics: attribution accuracy, false positives, false negatives, tracing
overhead, event coverage, and time-to-root-cause.

## 7. Takeaway

This work shows that request lifecycle traces can become auditable causal
evidence for LLM serving optimization.

