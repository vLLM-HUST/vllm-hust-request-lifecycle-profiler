# Protocol evidence and consumers

Historical numbers live in benchmark; maintained protocols keep configuration,
thresholds and failure rules. `NOT_M0_PROVEN`; Issue #19 mechanism `NO_GO` is
not topic `NO_GO`. No new run, installation-asset deletion or private-log
publication is part of this migration.

## Complete original documents

- [experiment_plan](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/842fc4bc69978e50e3b776731a962bfcf33ffaf3/archive/mod-targeted-20261023/profiler-protocols/snapshot/docs/experiment_plan.md)
- [g4_execution_spec](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/842fc4bc69978e50e3b776731a962bfcf33ffaf3/archive/mod-targeted-20261023/profiler-protocols/snapshot/docs/g4_execution_spec.md)
- [g6_counterfactual_spec](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/842fc4bc69978e50e3b776731a962bfcf33ffaf3/archive/mod-targeted-20261023/profiler-protocols/snapshot/docs/g6_counterfactual_spec.md)
- [issue19_public_evidence](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/842fc4bc69978e50e3b776731a962bfcf33ffaf3/archive/mod-targeted-20261023/profiler-protocols/snapshot/docs/issue19_public_evidence.md)
- [kv_recovery_runtime_callsite_map](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/842fc4bc69978e50e3b776731a962bfcf33ffaf3/archive/mod-targeted-20261023/profiler-protocols/snapshot/docs/kv_recovery_runtime_callsite_map.md)

## Legacy members

Each path below is an archive-relative identity, never a local checkout input.
The [machine-readable binding map](protocol_evidence_bindings.json) lists exact
matched members. A matched summary does not recover omitted raw captures.

- `.benchmarks/results/g1_cpu_controlled_trace_20260808/` — not present in the three pinned capsules; original not recovered.
- `.benchmarks/results/g2_readonly_admission_20260808/` — not present in the three pinned capsules; original not recovered.
- `.benchmarks/results/g3_minimum_online_trace_smoke_20260809/` — not present in the three pinned capsules; original not recovered.
- `.benchmarks/results/g4_fixed_8gib_modes_20260810/run_summary.json` — not present in the three pinned capsules; original not recovered.
- `.benchmarks/results/g5_capacity_surface_20260810/` — not present in the three pinned capsules; original not recovered.
- `.benchmarks/results/g6_counterfactual_20260811/` — not present in the three pinned capsules; original not recovered.
- `.benchmarks/results/m0_issue19_public/20260822-sanitized-corrected-paired-10/` — [evidence manifest](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/2144d58de108cddaff3800fdcbf12dc9d3ab1d18/archive/mod-consumers-20261023/profiler/manifest.json); [raw archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-mod-consumers-20261023-v1/profiler.tar.gz).
- `.benchmarks/results/npu6_controlled_fault_matrix/` — [collection manifest](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/812ef01ae992475d4ce6a3bb6a6ce4bda43b5f12/archive/mod-collections-20261023/profiler/manifest.json); [raw archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-mod-collections-20261023-v1/profiler.tar.gz).
- `.benchmarks/results/npu6_existing_server_probe_blocked/` — [history manifest](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/afd47a8e9964b71844dec75a8e908f279ae98202/archive/mod-history-20261023/profiler/manifest.json); [raw archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-mod-history-20261023-v1/profiler.tar.gz).
- `.benchmarks/results/npu6_existing_server_slow_stream_trace_smoke/` — [collection manifest](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/812ef01ae992475d4ce6a3bb6a6ce4bda43b5f12/archive/mod-collections-20261023/profiler/manifest.json); [raw archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-mod-collections-20261023-v1/profiler.tar.gz).
- `.benchmarks/results/npu6_existing_server_trace_overhead_smoke/` — [history manifest](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/afd47a8e9964b71844dec75a8e908f279ae98202/archive/mod-history-20261023/profiler/manifest.json); [raw archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-mod-history-20261023-v1/profiler.tar.gz).
- `.benchmarks/results/npu6_existing_server_trace_probe_repeated_smoke/` — [collection manifest](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/812ef01ae992475d4ce6a3bb6a6ce4bda43b5f12/archive/mod-collections-20261023/profiler/manifest.json); [raw archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-mod-collections-20261023-v1/profiler.tar.gz).
- `.benchmarks/results/npu6_existing_server_trace_probe_smoke/` — [collection manifest](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/812ef01ae992475d4ce6a3bb6a6ce4bda43b5f12/archive/mod-collections-20261023/profiler/manifest.json); [raw archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-mod-collections-20261023-v1/profiler.tar.gz).
- `.benchmarks/results/npu6_runtime_hook_pair_plan/` — [collection manifest](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/812ef01ae992475d4ce6a3bb6a6ce4bda43b5f12/archive/mod-collections-20261023/profiler/manifest.json); [raw archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-mod-collections-20261023-v1/profiler.tar.gz).
- `.benchmarks/results/npu6_runtime_hooks_concurrency_sweep/` — [collection manifest](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/812ef01ae992475d4ce6a3bb6a6ce4bda43b5f12/archive/mod-collections-20261023/profiler/manifest.json); [raw archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-mod-collections-20261023-v1/profiler.tar.gz).
- `.benchmarks/results/npu6_runtime_hooks_concurrency_sweep/concurrency_anomaly_analysis/` — [collection manifest](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/812ef01ae992475d4ce6a3bb6a6ce4bda43b5f12/archive/mod-collections-20261023/profiler/manifest.json); [raw archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-mod-collections-20261023-v1/profiler.tar.gz).
- `.benchmarks/results/npu6_runtime_hooks_decode_heavy_fault_smoke/` — [collection manifest](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/812ef01ae992475d4ce6a3bb6a6ce4bda43b5f12/archive/mod-collections-20261023/profiler/manifest.json); [raw archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-mod-collections-20261023-v1/profiler.tar.gz).
- `.benchmarks/results/npu6_runtime_hooks_disabled_low_overhead_baseline/` — [collection manifest](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/812ef01ae992475d4ce6a3bb6a6ce4bda43b5f12/archive/mod-collections-20261023/profiler/manifest.json); [raw archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-mod-collections-20261023-v1/profiler.tar.gz).
- `.benchmarks/results/npu6_runtime_hooks_long_prefill_fault_smoke/` — [collection manifest](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/812ef01ae992475d4ce6a3bb6a6ce4bda43b5f12/archive/mod-collections-20261023/profiler/manifest.json); [raw archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-mod-collections-20261023-v1/profiler.tar.gz).
- `.benchmarks/results/npu6_runtime_hooks_low_overhead_enabled_smoke/` — [collection manifest](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/812ef01ae992475d4ce6a3bb6a6ce4bda43b5f12/archive/mod-collections-20261023/profiler/manifest.json); [raw archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-mod-collections-20261023-v1/profiler.tar.gz).
- `.benchmarks/results/npu6_runtime_hooks_low_overhead_enabled_smoke/runtime_trace.jsonl` — [collection manifest](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/812ef01ae992475d4ce6a3bb6a6ce4bda43b5f12/archive/mod-collections-20261023/profiler/manifest.json); [raw archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-mod-collections-20261023-v1/profiler.tar.gz).
- `.benchmarks/results/npu6_runtime_hooks_prompt_heavy_low_output_diagnosis/` — [collection manifest](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/812ef01ae992475d4ce6a3bb6a6ce4bda43b5f12/archive/mod-collections-20261023/profiler/manifest.json); [raw archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-mod-collections-20261023-v1/profiler.tar.gz).
- `.benchmarks/results/npu6_runtime_hooks_prompt_heavy_low_output_smoke/` — [collection manifest](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/812ef01ae992475d4ce6a3bb6a6ce4bda43b5f12/archive/mod-collections-20261023/profiler/manifest.json); [raw archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-mod-collections-20261023-v1/profiler.tar.gz).
- `.benchmarks/results/npu6_runtime_hooks_slow_stream_fault_diagnosis/` — [collection manifest](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/812ef01ae992475d4ce6a3bb6a6ce4bda43b5f12/archive/mod-collections-20261023/profiler/manifest.json); [raw archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-mod-collections-20261023-v1/profiler.tar.gz).
- `.benchmarks/results/npu6_runtime_hooks_slow_stream_fault_smoke/` — [collection manifest](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/812ef01ae992475d4ce6a3bb6a6ce4bda43b5f12/archive/mod-collections-20261023/profiler/manifest.json); [raw archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-mod-collections-20261023-v1/profiler.tar.gz).
- `.benchmarks/results/npu6_runtime_hooks_structured_decode_fault_diagnosis/` — [collection manifest](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/812ef01ae992475d4ce6a3bb6a6ce4bda43b5f12/archive/mod-collections-20261023/profiler/manifest.json); [raw archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-mod-collections-20261023-v1/profiler.tar.gz).
- `.benchmarks/results/npu6_runtime_hooks_structured_decode_fault_smoke/` — [collection manifest](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/812ef01ae992475d4ce6a3bb6a6ce4bda43b5f12/archive/mod-collections-20261023/profiler/manifest.json); [raw archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-mod-collections-20261023-v1/profiler.tar.gz).
- `.benchmarks/results/npu6_slow_stream_trace_diagnosis/` — [collection manifest](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/812ef01ae992475d4ce6a3bb6a6ce4bda43b5f12/archive/mod-collections-20261023/profiler/manifest.json); [raw archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-mod-collections-20261023-v1/profiler.tar.gz).
- `.benchmarks/results/npu6_trace_diagnosis/` — [collection manifest](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/812ef01ae992475d4ce6a3bb6a6ce4bda43b5f12/archive/mod-collections-20261023/profiler/manifest.json); [raw archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-mod-collections-20261023-v1/profiler.tar.gz).
- `.benchmarks/results/npu6_trace_probe_preflight/` — [collection manifest](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/812ef01ae992475d4ce6a3bb6a6ce4bda43b5f12/archive/mod-collections-20261023/profiler/manifest.json); [raw archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-mod-collections-20261023-v1/profiler.tar.gz).
- `.benchmarks/results/synthetic_fault_injection_env/` — [collection manifest](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/812ef01ae992475d4ce6a3bb6a6ce4bda43b5f12/archive/mod-collections-20261023/profiler/manifest.json); [raw archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-mod-collections-20261023-v1/profiler.tar.gz).

G1/G4 private capture roots, the old temporary trace path and historical G4
server/client scripts are not public recovered inputs. Issue #19 raw server
logs and full device snapshots remain deliberately withheld; sanitized files
and redaction hashes do not grant access to those originals.

## Consumer inventory

- README, runbook, live-fault plan, roadmap and agent navigation keep the same
  document paths. The experiment plan retains G0–G6 methods and required fields;
  it no longer presents historical counters as current status.
- `verify_g0_pinned_pair.py` and the pinned scheduler compatibility document
  retain mode semantics. G4 capacity/configuration and G6 pass/fail thresholds
  are protocol inputs, not historical output data to remove.
- `make issue19-public-evidence-verify` still consumes verified external
  `BENCHMARK_EVIDENCE_ROOT` and recomputes the same scoped decision. No assertion,
  workload, sanitization or fixed gate was weakened.
- Existing Make readiness/probe producers generate new local ignored outputs;
  they must not overwrite downloaded archive roots or treat old READY markers
  as live admission. This migration does not execute those producers.
- The pinned call-site map is retained as implementation context; stage counts,
  source line numbers and byte budgets are not new performance results.
- Tests verify legacy binding membership against all three downloaded capsules
  and check the five document originals against their fixed manifest.

Remaining protocol/runbook documents and top-level research notes require their
own classification; this batch does not declare all mixed text migrated.
