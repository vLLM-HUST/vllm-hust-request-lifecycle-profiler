# M0 evaluation and preflight: evidence and consumers

Status remains NOT_M0_PROVEN. The fixed Issue19 mechanism remains NO_GO;
no treatment, device run or blind evaluation was started.

## Complete originals

- [docs/m0_evaluation_pipeline.md](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/5a4439b91923c5a1c5cf9a1a1dac729a3f32846c/archive/mod-targeted-20261023/profiler-m0-consumers/snapshot/docs/m0_evaluation_pipeline.md)
- [docs/issue19_m0_preflight.md](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/5a4439b91923c5a1c5cf9a1a1dac729a3f32846c/archive/mod-targeted-20261023/profiler-m0-consumers/snapshot/docs/issue19_m0_preflight.md)
- [.benchmarks/run_m0_development_validation.py](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/5a4439b91923c5a1c5cf9a1a1dac729a3f32846c/archive/mod-targeted-20261023/profiler-m0-consumers/snapshot/.benchmarks/run_m0_development_validation.py)

## Path roles and raw data

The [machine map](m0_consumer_evidence.json) separates inputs from outputs.

- `.benchmarks/results/m0_development_validation_20260811/validation.json`: historical-derived-output; not-in-four-pinned-capsules.
- `.benchmarks/results/m0_issue19_preflight/`: fresh-output-destination; output-not-archival-input.
- `/root/kv-recovery-service-g4/runs`: private-historical-input; not-in-four-pinned-capsules.
- `.benchmarks/results/npu6_runtime_hooks_concurrency_sweep/runtime_internal_spans.csv`: historical-input; archived.
  [Manifest](https://raw.githubusercontent.com/vLLM-HUST/vllm-hust-benchmark/812ef01ae992475d4ce6a3bb6a6ce4bda43b5f12/archive/mod-collections-20261023/profiler/manifest.json); [raw archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-mod-collections-20261023-v1/profiler.tar.gz).

The dated validation JSON was not matched in the evidence/history/collection/
research manifests. The old private G4 directory is absent on this machine;
its run identities cannot be recovered from the aggregate table. This bounded
absence is not proof of global loss. Do not fabricate inputs or overwrite the
historical table by rerunning a partial case. Private owners must supply exact
originals before authenticated reconstruction is possible.

## Maintained consumers

- The development driver uses explicit external roots and a new disjoint output.
  Its request-association heuristic remains diagnostic only; the migration does
  not make that heuristic causal proof. Missing run prefixes/client data/recovery
  spans or measured concurrency arms stop the run before output is written.
- Issue19 Make/CLI require a new external output before workload/environment
  inspection. Marker names and existing fail-closed serving checks remain; low-level
  writer tests may replace markers within their own temporary fixture directories.
- The installed `vllm-request-lifecycle-profiler-issue19-preflight` entrypoint
  calls that same CLI. The Issue19 baseline runner imports only scenario/seed/model
  constants from this module; those constants and serving behavior are unchanged.
- `docs/issue19_oasst1_workload.md` describes source pin, projection and tokenizer
  protocol, not a result table. Its version/capacity/request-count constants remain.
- `docs/entry_evidence.md` now forwards its former M0 queue here. The pipeline
  module and tests consume structured traces/fixtures, not Markdown score tables.
- Download roots remain read-only inputs. New derived/preflight outputs are not
  historical evidence, device approval or permission to repeat the scoped NO_GO.

Other protocol/implementation context and MOD consumers remain separate review.
No installation assets were deleted; missing G1/G4 records, old PDF identity,
private logs and hardware/review blockers remain disclosed in benchmark #326.
