# Findings — historical archive

[Complete historical original](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/c45a279dd2ee48c57a7cb27a0d7ad0666f25afd5/archive/mod-targeted-20261023/profiler-notes/snapshot/findings.md).
[Evidence and consumer map](docs/notes_evidence.md) distinguishes immutable
historical records, current methods and missing local artifacts. This page
does not claim a new experiment, build, visual review or device admission.

The original repository snapshot, numerical observations, paper-layout review,
build digest and offline-contract findings remain complete in benchmark.
Historical branch, environment, submodule and device statements are not facts
about the current checkout or its available hardware.

## Retained interpretation boundaries

- Existing-server probes and derived diagnoses are distinct from formal
  repository-controlled `real-online` evidence.
- Repeated requests within a scenario are not independent lifecycle trials.
- A concurrency-sensitive prefill tail is an observation, not controlled-fault
  ground truth or proof of a KV, scheduler, graph or kernel mechanism.
- Synthetic attribution does not establish live diagnosis accuracy. Missing
  queue/KV/cleanup coverage and unmeasured manual baselines remain visible in
  the archived audit rather than being silently filled in.
- Small client/runtime-hook pairs do not establish broad TPOT, CPU, host-memory
  or NPU-HBM overhead claims.
- A dominant span is `localization_only` without valid matched intervention
  linkage. The offline evaluator validates semantics, not server causality.
- Historical PDF rendering/build statements are not repeated here as current
  verification; the old digest differs from the known archived PDF.

See [the current claim ledger](docs/claim_ledger.md) and
[blind contract](docs/blind_attribution_contract.md) for maintained claims and
methods. `NOT_M0_PROVEN` and the scoped Issue #19 `NO_GO` remain unchanged.
