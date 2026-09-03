# Request Lifecycle Causal Profiler

This repository is an incubation observability/artifact line for causal request
lifecycle tracing in LLM serving. It targets a single-NPU first implementation
on NPU6 and follows the optimization-repository workflow used by the
`llm-optimizations` workspace.

## Current research focus

The profiler owns low-overhead state feedback and causal attribution. It may
export inputs to roofline and statistical-gate projects, but trace ownership
alone does not make those contributions complete. The current implementation
focus is an optional KV-recovery profile connected to the runtime
`OffloadingConnector` path. It is default-off and becomes active only when the
profiler environment and runtime `additional_config` both opt in. CPU
integration tests precede service and hardware measurements. Controlled
intervention-based attribution remains the evaluation goal. See
[`RESEARCH_UPGRADE_20260727.md`](RESEARCH_UPGRADE_20260727.md).

The corrected Issue #19 experiment is an evidence-valid mechanism `NO_GO`:
resource pathology appeared in 1/10 matched repetitions and latency pathology
in 0/10, below the preregistered 8/10 gate. Reconciliation remains disabled
for that fixed worker-exit-last specialty scenario. This decision does not
reject the broader Request Lifecycle research topic.

## Research Question

Can request-level lifecycle traces be converted into causal bottleneck
attribution for LLM serving, so optimization work targets the true limiting
stage instead of correlated symptoms?

## Repository Map

- Development and performance-evidence policy: see the workspace-level
  `AGENTS.md` (kept local; not part of this repository).
- `src/vllm_request_lifecycle_profiler/`: trace schema, attribution logic, and
  plugin code.
- `contracts/`: historical design notes retained only for technical context;
  they are not approval or activation gates.
- `.benchmarks/`: trace probes and controlled fault-injection entrypoints.
- `third_party/llm-serving-workloads/`: pinned shared workload suite.
- `third_party/vllm-hust/`: pinned historical vLLM-HUST hook carrier used only
  as a reviewed patch/evidence reference; new integration starts from current
  runtime main.
- `tests/`: no-NPU trace and repository tests.
- `docs/research_logic.md`: seven-step research framing.
- `docs/experiment_plan.md`: evaluation plan and evidence labels.
- `docs/claim_ledger.md`: current claims and forbidden wording.
- `docs/issue19_public_evidence.md`: sanitized Issue #19 evidence and its
  durable, scenario-scoped decision boundary.
- `docs/runtime_fault_attribution_roadmap.md`: path from complete runtime
  hooks to controlled-fault attribution evidence.
- `paper/request_lifecycle_causal_profiler/`: systems-paper scaffold.

## Current Mechanism

For
[benchmark #134](https://github.com/vLLM-HUST/vllm-hust-benchmark/issues/134),
`kv_recovery.py` adds an optional pressure-episode schema alongside the base
lifecycle trace. It validates stable request/sequence/block identity and
decomposes copy, restore-to-wakeup, wakeup-to-admission, admission-to-first-
compute, and requeue time. Keeping this optional avoids making historical
non-pressure traces appear incomplete.

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

### KV-recovery configuration

The optional runtime path is disabled unless both sides opt in. Configure the
profiler process with:

```bash
export VLLM_RLP_TRACE_EXPORT_PATH=/path/to/trace
export VLLM_RLP_COMMUNICATION_MODE=issue2:kv-recovery-v1alpha1
export VLLM_RLP_KV_RECOVERY_RUN_ID=0123456789abcdef0123456789abcdef
export VLLM_RLP_PROFILER_PARENT_COMMIT=<40-lowercase-hex-commit>
export VLLM_RLP_RUNTIME_CORE_COMMIT=<40-lowercase-hex-commit>
export VLLM_RLP_DEVICE_PLUGIN_COMMIT=<40-lowercase-hex-commit>
```

The vLLM runtime configuration must also contain:

```json
{
  "kv_recovery_profile_enabled": true,
  "recompute_scheduler_enable": false
}
```

The connector must resolve to `OffloadingConnector` with
`TieringOffloadingSpec`. Omitting the profiler mode, run ID, runtime switch, or
supported spec keeps the observer disabled. Initialization and observation
failures disable profiling without failing serving.

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

## Next step

Complete the normal configuration path for the optional KV-recovery profiler,
keep the disabled serving path unchanged, and validate the whole runtime-to-
profile chain on CPU. After the implementation and CI are stable, run a small
NPU service smoke before matched performance experiments. Performance claims
must follow the cross-repository benchmark performance policy (workspace-level
`AGENTS.md`, kept local).

The checked-in hook-enabled NPU6 artifacts remain useful contaminated
development evidence: the smoke pair has complete historical chains and a
small-workload smoke delta observed once per mode. They are not primary
blind-localization cases and do not prove M0. New controlled-live scoring
requires fresh cases and a reproducible target configuration.
