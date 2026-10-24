# Runbook evidence and consumers

`NOT_M0_PROVEN`. Historical smoke and client-proxy observations are not current
device admission, blind accuracy, or serving-speedup results. Issue #19 scoped
mechanism `NO_GO` is not topic `NO_GO`; no workload/gate is changed here.

## Complete originals

- [live_fault_matrix_plan](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/76056993c6bdf615850d683e49c46febf0ce96d3/archive/mod-targeted-20261023/profiler-runbooks/snapshot/docs/live_fault_matrix_plan.md)
- [next_agent_task](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/76056993c6bdf615850d683e49c46febf0ce96d3/archive/mod-targeted-20261023/profiler-runbooks/snapshot/docs/next_agent_task.md)
- [blind_attribution_execution](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/76056993c6bdf615850d683e49c46febf0ce96d3/archive/mod-targeted-20261023/profiler-runbooks/snapshot/docs/blind_attribution_execution.md)
- [npu6_trace_probe_runbook](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/76056993c6bdf615850d683e49c46febf0ce96d3/archive/mod-targeted-20261023/profiler-runbooks/snapshot/docs/npu6_trace_probe_runbook.md)

## Exact legacy paths

The [machine binding map](runbook_evidence_bindings.json) lists matching members
and distinguishes input from output. Output examples are not recovered runs,
even when a similarly named historical directory exists in a capsule.

- `.benchmarks/results/npu6_runtime_hooks_concurrency_sweep/` (docs/live_fault_matrix_plan.md): **historical-input**, archived. [collection manifest](https://raw.githubusercontent.com/vLLM-HUST/vllm-hust-benchmark/812ef01ae992475d4ce6a3bb6a6ce4bda43b5f12/archive/mod-collections-20261023/profiler/manifest.json); [raw archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-mod-collections-20261023-v1/profiler.tar.gz)
- `.benchmarks/results/npu6_runtime_hooks_concurrency_sweep/concurrency_anomaly_analysis/` (docs/live_fault_matrix_plan.md): **historical-input**, archived. [collection manifest](https://raw.githubusercontent.com/vLLM-HUST/vllm-hust-benchmark/812ef01ae992475d4ce6a3bb6a6ce4bda43b5f12/archive/mod-collections-20261023/profiler/manifest.json); [raw archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-mod-collections-20261023-v1/profiler.tar.gz)
- `.benchmarks/results/npu6_runtime_hooks_decode_heavy_fault_smoke/` (docs/live_fault_matrix_plan.md): **historical-input**, archived. [collection manifest](https://raw.githubusercontent.com/vLLM-HUST/vllm-hust-benchmark/812ef01ae992475d4ce6a3bb6a6ce4bda43b5f12/archive/mod-collections-20261023/profiler/manifest.json); [raw archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-mod-collections-20261023-v1/profiler.tar.gz)
- `.benchmarks/results/npu6_runtime_hooks_long_prefill_fault_smoke/` (docs/live_fault_matrix_plan.md): **historical-input**, archived. [collection manifest](https://raw.githubusercontent.com/vLLM-HUST/vllm-hust-benchmark/812ef01ae992475d4ce6a3bb6a6ce4bda43b5f12/archive/mod-collections-20261023/profiler/manifest.json); [raw archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-mod-collections-20261023-v1/profiler.tar.gz)
- `.benchmarks/results/issue1_blind_attribution_development/local-01` (docs/blind_attribution_execution.md): **fresh-output-example**, output-not-archival-input. No matching member in the three fixed capsules.
- `.benchmarks/results/issue1_preblind_noise_calibration/summary.json` (docs/blind_attribution_execution.md): **historical-input**, archived. [collection manifest](https://raw.githubusercontent.com/vLLM-HUST/vllm-hust-benchmark/812ef01ae992475d4ce6a3bb6a6ce4bda43b5f12/archive/mod-collections-20261023/profiler/manifest.json); [raw archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-mod-collections-20261023-v1/profiler.tar.gz)
- `.benchmarks/results/npu6_runtime_hooks_enabled_smoke/runtime_trace.jsonl` (docs/npu6_trace_probe_runbook.md): **fresh-output-example**, output-not-archival-input. [collection manifest](https://raw.githubusercontent.com/vLLM-HUST/vllm-hust-benchmark/812ef01ae992475d4ce6a3bb6a6ce4bda43b5f12/archive/mod-collections-20261023/profiler/manifest.json); [raw archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-mod-collections-20261023-v1/profiler.tar.gz)
- `.benchmarks/results/npu6_trace_probe_preflight` (docs/npu6_trace_probe_runbook.md): **fresh-output-example**, output-not-archival-input. [collection manifest](https://raw.githubusercontent.com/vLLM-HUST/vllm-hust-benchmark/812ef01ae992475d4ce6a3bb6a6ce4bda43b5f12/archive/mod-collections-20261023/profiler/manifest.json); [raw archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-mod-collections-20261023-v1/profiler.tar.gz)
- `/tmp/codex-vllm-request-lifecycle-profiler-npu6-trace.jsonl` (docs/npu6_trace_probe_runbook.md): **historical-input**, not-in-pinned-capsules. No matching member in the three fixed capsules.

## Calibration input

The historical public summary member is
`.benchmarks/results/issue1_preblind_noise_calibration/summary.json` under
verified `BENCHMARK_COLLECTION_ROOT`. Use the collection manifest and raw
archive above and [EVIDENCE.md](../EVIDENCE.md) for size/SHA-verified retrieval.
Its presence does not recover withheld raw logs, process/device/port identities
or private host paths. It is not a new calibration or blind success.

## Consumers and output ownership

- `.github/agents/request-lifecycle-profiler.agent.md` and `TOP_TIER_PUSH_PLAN.md`
  continue to point to `next_agent_task.md`. That page links the scoped Issue19
  evidence and this input/output map; the research sequence does not authorize
  hardware work in a document-only task.
- `experiment_plan.md` and `claim_ledger.md` retain their runbook/plan paths.
  The legacy schema, current whole-trace warning, ownership and request-ID
  requirements remain; a legacy READY marker is not KV-recovery admission.
- The blind development runner reads the synthetic fixture and vocabulary,
  not historical result directories. Its exclusive-create writer rejects file
  reuse. The example chooses a fresh external output, never an archive root.
- The calibration runner retains its frozen target and scorer thresholds;
  it creates new results only in an explicitly chosen output directory.
- The preflight checks endpoint/model/trace/device state and writes readiness
  metadata. Its output directory is writable and may have markers replaced;
  only a fresh run-owned external destination is suitable. The Make target's
  legacy default is not an archival input or evidence of a recovered run.
- Fault-matrix and paper consumers already read verified external collection
  inputs. Their tests and fixed Issue19 NO_GO assertion remain unchanged.

No serving process, device probe, calibration or historical launcher was run.
The old temporary trace is not recovered from summaries; prior G1/G4 raw gaps,
private Issue19 logs and hardware/review blockers remain. Other top-level
research notes are a separate mixed-document queue, not declared migrated here.
