# Research upgrade: shared causal measurement plane

[Complete historical original](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/c45a279dd2ee48c57a7cb27a0d7ad0666f25afd5/archive/mod-targeted-20261023/profiler-notes/snapshot/RESEARCH_UPGRADE_20260727.md).
[Evidence and consumer map](docs/notes_evidence.md) distinguishes immutable
historical records, current methods and missing local artifacts. This page
does not claim a new experiment, build, visual review or device admission.

## Primary opportunity

The historical work-package labels and ownership assertions are preserved in
the original; they are not benchmark baseline/candidate identities. The method
here is a shared request-level measurement plane. Supplying measurements to
serving-roofline or statistical models does not establish those models' full
research contribution or their validation.

## Seven-step boundary

1. **Problem:** request metrics cannot distinguish queue, prefill, decode,
   communication, KV, transfer, graph, or client causes.
2. **Importance:** optimizing a correlated symptom wastes accelerator time and
   can worsen the true bottleneck.
3. **Gap:** current dominant-span attribution is deterministic localization,
   not causal diagnosis.
4. **Idea:** expose a stable low-overhead event schema and validate attribution
   through controlled stage interventions and counterfactual replay.
5. **Feasibility:** use the archived hook/pair observations as development
   context; verify the actual current runtime before any authorized extension.
6. **Evaluation:** blinded known/false regressions, trace-off overhead,
   controlled interventions, attribution precision/recall, localization time,
   and request-level effects.
7. **Takeaway gate:** causal serving diagnosis requires intervention-linked
   cross-layer state, not the longest observed span alone.

## Shared-interface contract

- Export versioned phase spans, resource counters, graph identity, workload
  arrival semantics, and correlation IDs.
- Keep project-specific policy decisions outside this repository.
- Feed A1/C3 models through stable artifacts; do not absorb their papers merely
  because they consume profiler events.

The immediate gate remains controlled live attribution. More trace fields alone
do not constitute progress.

Current scope and evidence status: [research sequence](docs/next_agent_task.md)
and [claim ledger](docs/claim_ledger.md). `NOT_M0_PROVEN`; this methodological
proposal is not a new measured result.
