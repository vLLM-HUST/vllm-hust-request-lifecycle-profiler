# Top-level notes: evidence and consumers

The notes are historical records, not current device admission, performance
qualification or a new execution queue. `NOT_M0_PROVEN`; scoped Issue #19
mechanism `NO_GO` is preserved. Source methods and artifact ownership remain
distinct from archived numeric observations.

## Complete originals

- [TOP_TIER_PUSH_PLAN.md](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/c45a279dd2ee48c57a7cb27a0d7ad0666f25afd5/archive/mod-targeted-20261023/profiler-notes/snapshot/TOP_TIER_PUSH_PLAN.md)
- [RESEARCH_UPGRADE_20260727.md](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/c45a279dd2ee48c57a7cb27a0d7ad0666f25afd5/archive/mod-targeted-20261023/profiler-notes/snapshot/RESEARCH_UPGRADE_20260727.md)
- [progress.md](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/c45a279dd2ee48c57a7cb27a0d7ad0666f25afd5/archive/mod-targeted-20261023/profiler-notes/snapshot/progress.md)
- [findings.md](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/c45a279dd2ee48c57a7cb27a0d7ad0666f25afd5/archive/mod-targeted-20261023/profiler-notes/snapshot/findings.md)
- [task_plan.md](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/c45a279dd2ee48c57a7cb27a0d7ad0666f25afd5/archive/mod-targeted-20261023/profiler-notes/snapshot/task_plan.md)

## Explicit legacy inputs

The [machine binding map](notes_evidence_bindings.json) identifies exact
archive members. Read them through verified external roots in [EVIDENCE.md](../EVIDENCE.md).

- `.benchmarks/results/npu6_runtime_hook_pair_plan/summary.json` in `TOP_TIER_PUSH_PLAN.md`: archived. [collection manifest](https://raw.githubusercontent.com/vLLM-HUST/vllm-hust-benchmark/812ef01ae992475d4ce6a3bb6a6ce4bda43b5f12/archive/mod-collections-20261023/profiler/manifest.json); [raw archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-mod-collections-20261023-v1/profiler.tar.gz).
- `.benchmarks/results/npu6_controlled_fault_matrix/` in `progress.md`: archived. [collection manifest](https://raw.githubusercontent.com/vLLM-HUST/vllm-hust-benchmark/812ef01ae992475d4ce6a3bb6a6ce4bda43b5f12/archive/mod-collections-20261023/profiler/manifest.json); [raw archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-mod-collections-20261023-v1/profiler.tar.gz).
- `.benchmarks/results/npu6_controlled_fault_matrix/` in `findings.md`: archived. [collection manifest](https://raw.githubusercontent.com/vLLM-HUST/vllm-hust-benchmark/812ef01ae992475d4ce6a3bb6a6ce4bda43b5f12/archive/mod-collections-20261023/profiler/manifest.json); [raw archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-mod-collections-20261023-v1/profiler.tar.gz).

## Historical PDF identity

The original progress/findings notes record SHA256 `b4da67d59a466b107bd5e8a4d3e3236b39ed1b397415d7099ad5dcba6543cf71` and the old
local copy `/home/shuhao/llm-optimizations/docs/papers/08-vllm-request-lifecycle-profiler-plugin__request_lifecycle_causal_profiler.pdf`. That digest does not match any file in the four pinned
evidence/history/collection/research manifests checked in this migration.
The [research archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-profiler-research-20261024-v1/profiler-research-20261024.tar.gz) contains
`snapshot/paper/request_lifecycle_causal_profiler/request_lifecycle_causal_profiler.pdf` with SHA256 `293d538f9fac6e21a83926dcd5958cc940cbdaab9469310d9b28de3284ae0988` instead.
These are different byte identities. The known archived PDF is not a recovered
copy of the old build; the local path and historical rendering claim remain
unverified here. No PDF was rebuilt or visually reviewed in this migration.

## Consumer inventory

- `docs/runbook_evidence.md` keeps its reference to `TOP_TIER_PUSH_PLAN.md`;
  that stable entry now separates current research scope from historical gates.
- `progress.md`, `findings.md` and `task_plan.md` remain stable planning/history
  navigation for agents. Git search found no script, test or Makefile parsing
  these notes as numerical inputs; their old completion tables are not gates.
- `RESEARCH_UPGRADE_20260727.md` keeps its methodological seven-step structure
  and shared-interface contract; historical work-package labels are not B0/B1
  benchmark identities or claims of validated downstream models.
- `make top-tier-readiness` generates a new derived audit;
  `make paper-assets` produces a new paper projection from explicit verified
  inputs. The archived notes are not executable inputs or new output locations.
  Existing external-data, claim and paper-consumer tests remain in place.
- `PROJECT_BRIEF.md` is retained as a research question, method and stop/go
  protocol rather than treated as a measurement file. Current source rules in
  `AGENTS.md` take precedence over the historical notes' old process statements.

Historical fault-matrix coverage, invalid/failed cases, coarse-tail limits,
synthetic-only claims and unmeasured overhead/manual baselines remain in the
unchanged originals and current claim ledger. Other MOD data consumers and
private/missing G1/G4 inputs remain separate work; no archive or installation
asset is deleted and no new hardware work is authorized here.
