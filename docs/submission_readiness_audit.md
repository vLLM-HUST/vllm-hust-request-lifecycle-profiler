# Request-Lifecycle Profiler Submission Readiness Audit

Date: 2026-07-26

## Verdict

**Research draft; not a submission candidate.**

The current artifact supports a request-lifecycle method, three controlled
existing-server scenario correspondences, and localization of a
concurrency-sensitive tail to the coarse runtime prefill span. It does not
support live internal diagnosis accuracy, a scheduler/KV/graph/kernel root
cause, broad overhead, or a conference-ready evaluation.

No hardware experiment was launched during this audit. The checked-in source
artifacts remain `existing-server-probe`, and the new analyses and paper assets
remain `derived-artifact`.

## Evidence That Is Currently Supported

- Injected slow client reads: client-visible streaming diagnosis for 4/4
  measured requests; 5/5 complete runtime-hook chains.
- Decode-heavy output contrast: decode diagnosis for 4/4 measured requests;
  5/5 complete runtime-hook chains.
- Prompt-heavy, low-output contrast: prefill diagnosis for 8/8 measured
  requests; 9/9 complete runtime-hook chains.
- Concurrency sweep: two greater-than-one-second tails at concurrency 2 are
  inside the `scheduled` to `prefill_done` interval. Runtime prefill p95 is
  12,261.98 ms at concurrency 2, versus 150.31 and 106.94 ms at concurrency 1
  and 3.

Repeated requests within a scenario share workload configuration and server
state. The request counts above are therefore not independent trials and must
not be reported as an estimate of population diagnosis accuracy.

## Evidence That Is Not Supported

- Queue-pressure, KV-pressure, or cleanup diagnosis with repository-controlled
  online ground truth.
- A substage root cause for the concurrency-2 tail. Current traces cannot
  distinguish scheduler handoff, KV allocation/cache pressure, graph or batch
  transition, and device prefill execution.
- Formal graph-mode evidence. Existing-server manifests do not establish
  launch custody or execution mode.
- A diagnosis-time advantage over raw logs, timer-only diagnosis,
  causal-rules-disabled diagnosis, or timed human diagnosis.
- TPOT, CPU, host-memory, NPU-HBM, or broad-workload runtime-hook overhead.
  The client pair measures client-probe event construction; the separate
  runtime pair is only a 12-request smoke.

## Repository Changes

- Added a derived controlled-fault coverage audit with explicit missing
  queue/KV/cleanup gates and regression tests.
- Extended the concurrency analyzer with four falsifiable sub-prefill
  instrumentation requirements while keeping `root_cause_status=unresolved`.
- Added no-hardware readiness gates for the coverage audit and unresolved tail
  boundary.
- Rewrote the paper around the aggregate-timer ambiguity, ordered events plus
  completeness/causal rules, and two supported results.
- Reduced the main paper from eight micro-tables to two readable displays.
- Added related-work positioning, a generative-AI disclosure, moderate
  hyphenation penalties, and an explicit research-draft verdict.
- Added PDF canonicalization that reconstructs the document page by page with
  pypdf, drops volatile creation metadata, and preserves embedded fonts.

## Verification

- `make lint`: passed.
- `make test`: 32 passed.
- `make shared-workloads-smoke`: passed.
- `make top-tier-readiness`: passed and reported 4/7 available audit rows,
  missing queue/KV/cleanup, prefill localization, and unresolved root cause.
- Two complete `make -C paper/request_lifecycle_causal_profiler pdf` builds:
  identical SHA-256
  `b4da67d59a466b107bd5e8a4d3e3236b39ed1b397415d7099ad5dcba6543cf71`.
- Final PDF: three pages, all fonts embedded, no overfull boxes, undefined
  references, or multiply-defined labels.
- Visual inspection: all three rendered pages checked at 144 dpi; tables,
  captions, columns, references, and final-page balance are readable without
  clipping or overlap.

Central PDF:

`/home/shuhao/llm-optimizations/docs/papers/08-vllm-request-lifecycle-profiler-plugin__request_lifecycle_causal_profiler.pdf`

## Exact Scientific Blocker and Next Protocol

Before any hardware run, freeze a repository-controlled graph-mode protocol
that:

1. launches and owns the exact serving process and records its runtime,
   submodule, model, graph-mode, and environment identity;
2. adds queue-pressure, KV-pressure, and cleanup injections with observable
   ground truth;
3. records raw logs, simple timers, causal rules disabled, and timed manual
   diagnosis for the same requests;
4. splits coarse prefill into scheduler dispatch/worker start, KV allocation
   and free-block state, graph key/capture and batch-shape transition, and
   device prefill start/end;
5. defines repetitions and aggregation before execution; and
6. admits a run only after NPU0--6 are confirmed free. NPU7 is prohibited.

Until this protocol is frozen, paper churn should stop.
