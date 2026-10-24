# Entry documentation: evidence and consumers

Five complete originals retain historical numbers, failure records, software
versions and legacy instructions. `NOT_M0_PROVEN`; Issue #19 remains a scoped
mechanism `NO_GO`. ABI versions and protocol thresholds are not measurements.

## Originals

- [README.md](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/db79a80ae22f974e31d19fd84ba2a20ed919290c/archive/mod-targeted-20261023/profiler-entry-docs/snapshot/README.md)
- [CHANGELOG.md](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/db79a80ae22f974e31d19fd84ba2a20ed919290c/archive/mod-targeted-20261023/profiler-entry-docs/snapshot/CHANGELOG.md)
- [.benchmarks/README.md](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/db79a80ae22f974e31d19fd84ba2a20ed919290c/archive/mod-targeted-20261023/profiler-entry-docs/snapshot/.benchmarks/README.md)
- [docs/research_logic.md](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/db79a80ae22f974e31d19fd84ba2a20ed919290c/archive/mod-targeted-20261023/profiler-entry-docs/snapshot/docs/research_logic.md)
- [docs/runtime_fault_attribution_roadmap.md](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/db79a80ae22f974e31d19fd84ba2a20ed919290c/archive/mod-targeted-20261023/profiler-entry-docs/snapshot/docs/runtime_fault_attribution_roadmap.md)

## Raw inputs

[Collection manifest](https://raw.githubusercontent.com/vLLM-HUST/vllm-hust-benchmark/812ef01ae992475d4ce6a3bb6a6ce4bda43b5f12/archive/mod-collections-20261023/profiler/manifest.json) and
[raw collection archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-mod-collections-20261023-v1/profiler.tar.gz) preserve the exact members
listed in [the machine map](entry_evidence_bindings.json). Paths in that map
are relative to verified external `BENCHMARK_COLLECTION_ROOT`, not this checkout.
The README Issue19 decision uses the public export in [EVIDENCE.md](../EVIDENCE.md)
and [public evidence](issue19_public_evidence.md); private logs remain withheld.

## Consumer classification

- `pyproject.toml` reads README for package metadata. Its stable path and ECPA
  compatibility identity remain unchanged; builds include updated navigation.
- CHANGELOG is release history, not an executable paper input. Version/API
  numbers remain. The obsolete local changelog path is preserved in its original.
- `make npu6-runtime-hook-pair-plan` already reads explicit external collection
  roots. Its derived outputs are not replacements for archived inputs.
- `make top-tier-readiness` runs tests and generates derived assets, not a
  read-only audit. The stale checked-in-input and ready claims are removed.
- `make paper-assets` and `paper-pdf` follow [paper/README.md](../paper/README.md).
  The generic `scripts/render_placeholder_paper_scaffold.py` is a template
  generator, not a historical-data consumer or current paper rebuild step.
  It can overwrite scaffolding and was not executed; its old workspace-export
  template must not be substituted for the maintained isolated rebuild path.
- README navigation to research logic and roadmap remains stable. Their
  historical measurements are not parsed as numerical build inputs. Failed
  candidates and coarse attribution limits remain in the originals and map.
- `agent.md` is a compatibility pointer to tracked AGENTS; no empirical table
  was found there. Method/schema documents are not deleted for containing
  numerical protocol parameters. Other remaining documents need separate review.

## Remaining mixed consumer queue

`docs/m0_evaluation_pipeline.md` still cites a dated development-validation
output and an old unit-test count; its generator is
`.benchmarks/run_m0_development_validation.py`. This needs a separate original
snapshot and input/output classification, not an unverified recovery claim.
`docs/issue19_m0_preflight.md` describes the ignored output directory produced
by the Make preflight target; that path is a generation destination rather than
proof of an archived result. No old preflight was rerun here.

No hardware run, paper compile, website release or asset deletion occurred.
Missing G1/G4 inputs, old PDF identity and private raw logs are not recovered
by these narrative snapshots. No zero-consumer installation-asset claim is made.
