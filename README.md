# Request Lifecycle Causal Profiler

This repository is an incubation observability/artifact line for causal request
lifecycle tracing in LLM serving. It targets a single-NPU first implementation
on NPU6 and follows the optimization-repository workflow used by the
`llm-optimizations` workspace.

## 2026-07-27 research focus

The profiler directly owns the low-overhead state feedback and causal
attribution questions. It may export inputs to roofline and statistical-gate
projects, but trace ownership alone does not make those contributions complete.
The immediate gate remains controlled intervention-based attribution. See
[`RESEARCH_UPGRADE_20260727.md`](RESEARCH_UPGRADE_20260727.md).

## Research Question

Can request-level lifecycle traces be converted into causal bottleneck
attribution for LLM serving, so optimization work targets the true limiting
stage instead of correlated symptoms?

## Repository Map

- `src/vllm_request_lifecycle_profiler/`: trace schema, attribution logic, and
  plugin code.
- `.benchmarks/`: trace probes and controlled fault-injection entrypoints.
- `third_party/llm-serving-workloads/`: pinned shared workload suite.
- `third_party/vllm-hust/`: pinned vLLM-HUST runtime carrier with optional
  lifecycle hook sites on `feature/request-lifecycle-profiler-runtime-hooks-faculty`.
- `tests/`: no-NPU trace and repository tests.
- `docs/research_logic.md`: seven-step research framing.
- `docs/experiment_plan.md`: evaluation plan and evidence labels.
- `docs/claim_ledger.md`: current claims and forbidden wording.
- `docs/runtime_fault_attribution_roadmap.md`: path from complete runtime
  hooks to controlled-fault attribution evidence.
- `paper/request_lifecycle_causal_profiler/`: systems-paper scaffold.

## Current Mechanism

The initial profiler represents each request as ordered lifecycle events and
computes complete stage spans. The first attribution rule reports the dominant
lifecycle span with a reason code. This is intentionally deterministic so
controlled fault-injection experiments can validate it.

`make offline-intervention-gate` additionally evaluates a CPU-only matched
control/intervention fixture. Its output keeps `dominant_span_localization`
separate from `causal_evidence`: an unpaired long span remains
`localization_only`, while a declared single-stage intervention must produce
the target delta without changing other spans. This is `simulation/model`
readiness and remains `NOT_M0_PROVEN`; it is not controlled live attribution.

## NPU and Environment

- Reserved device: NPU6.
- Project environment: `vllm-request-lifecycle-profiler-exp`.
- The shared `vllm-hust-dev` environment may be cloned as a baseline, but
  project overlays must not be installed into it.

## Shared Workloads

Use the pinned `third_party/llm-serving-workloads` submodule as the default
workload source. Repo-local workloads are allowed only for controlled
fault-injection cases. For workspace convenience, `WORKLOAD_REPO` or
`LLM_SERVING_WORKLOADS_SRC` may point at a sibling checkout, but paper evidence
must record the pinned submodule commit.

## Evidence Discipline

Every experiment must carry one evidence label: `real-online`,
`existing-server-probe`, `replay`, `simulation/model`, `projected-profile`, or
`derived-artifact`. Profiler-only results are diagnosis evidence, not runtime
speedups.

## Test

```bash
PYTHONPATH=src pytest -q
make shared-workloads-smoke PYTHON=python3
```

## Next Gate

The hook-enabled NPU6 runtime gate is now satisfied for the smoke path:
`.benchmarks/results/npu6_runtime_hook_pair_plan/summary.json` reports complete
chains for all observed request chains and bounded TTFT/latency overhead on the
matched hook-disabled/enabled workload shape.

The next gate is controlled live attribution. Use the pinned
`third_party/vllm-hust` runtime hook branch on NPU6, inject one fault class at a
time, and compare internal runtime spans against client-observed anchors. Start
with slow streaming, long-prompt prefill pressure, or decode-heavy output; then
add KV-pressure and cleanup stalls. Run `make top-tier-readiness` before and
after each evidence batch.
