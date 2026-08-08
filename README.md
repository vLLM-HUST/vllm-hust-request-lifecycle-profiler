# Request Lifecycle Causal Profiler

This repository is an incubation observability/artifact line for causal request
lifecycle tracing in LLM serving. It targets a single-NPU first implementation
on NPU6 and follows the optimization-repository workflow used by the
`llm-optimizations` workspace.

## 2026-08-03 research focus

The profiler directly owns the low-overhead state feedback and causal
attribution questions. It may export inputs to roofline and statistical-gate
projects, but trace ownership alone does not make those contributions complete.
The minimal M0 phase/runtime protocol in `contracts/p0/` is owner-frozen. The
parent exporter has an audited local CPU checkpoint. Following the two newest
faculty comments on issue #1, merged PR #4 is now composed with that checkpoint
on `feature/kv-recovery-integration`. The immediate gate is to freeze a
compatible optional KV-recovery profile and connect its complete request/stage
chain to a controlled runtime trace before any tiering/HBM-only matched
experiment. Controlled intervention-based attribution remains the formal
evaluation gate after P1 instrumentation. See
[`RESEARCH_UPGRADE_20260727.md`](RESEARCH_UPGRADE_20260727.md).

## Research Question

Can request-level lifecycle traces be converted into causal bottleneck
attribution for LLM serving, so optimization work targets the true limiting
stage instead of correlated symptoms?

## Repository Map

- `AGENTS.md`: durable assignment, ownership, environment, evidence, and merge
  policy for all later work.
- `src/vllm_request_lifecycle_profiler/`: trace schema, attribution logic, and
  plugin code.
- `contracts/p0/`: owner-frozen minimum M0 phase/runtime protocol, approval
  record, and historical development-case inventory.
- `.benchmarks/`: trace probes and controlled fault-injection entrypoints.
- `third_party/llm-serving-workloads/`: pinned shared workload suite.
- `third_party/vllm-hust/`: pinned historical vLLM-HUST hook carrier used only
  as a reviewed patch/evidence reference; new integration starts from current
  runtime main.
- `tests/`: no-NPU trace and repository tests.
- `docs/research_logic.md`: seven-step research framing.
- `docs/experiment_plan.md`: evaluation plan and evidence labels.
- `docs/claim_ledger.md`: current claims and forbidden wording.
- `docs/runtime_fault_attribution_roadmap.md`: path from complete runtime
  hooks to controlled-fault attribution evidence.
- `docs/host_device_clock_calibration.md`: Ascend marker collection,
  profiler connectionId resolution, robust-window gates, and audit procedure.
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

## Cross-clock idle evidence

The package now provides an opt-in `AscendClockMarkerCollector` for host
brackets around device-visible timeline events. The matching TraceLoom analyzer
resolves each profiled `aclrtRecordEvent` through a unique connectionId to
`TASK.startNs`, fits an explicit profiler-host→caller-realtime→device composed
clock model, and admits host API evidence only through robust overlap/delay
windows whose epsilon includes both clock legs. Raw device syscnt is never
accepted as profiler nanoseconds. Three repeated real NPU6 captures now pass
the composed-clock replay and strengthened SQL audit with both component and
end-to-end holdout distributions. Replaying the eager serving capture reduces
the old 1133 queued-delay slices to one 93.407 μs diagnostic slice, showing why
the clock-domain correction is material. That source still has
`analysis_status=invalid_input` because of zero-duration device tasks, so it is
not accepted full-run E4 evidence. See
[`docs/host_device_clock_calibration.md`](docs/host_device_clock_calibration.md).

## Test

```bash
PYTHONPATH=src pytest -q
make shared-workloads-smoke PYTHON=python3
```

## Next Gate

The P0 owner freeze is recorded in
[`owner-freeze-approval.json`](contracts/p0/owner-freeze-approval.json). It
pins the minimum runtime contract SHA-256
`122963930919073179d4844422d21e85da3a522def3ace723eb992eac43cdade`,
phase taxonomy SHA-256
`82aae94c5d124b846f77684e239714d51791115608e786079c4ea4bd4ca05abd`,
runtime `f229ba7cad21a4dba58681af6738a9fd947388e2`, device plugin
`cafad89a5e103f31ea517c1edb56130578c3cd56`, and
`communication_mode=none`. Those pins remain valid for the existing P1
checkpoint, but actual tiering/offload is outside the frozen mode. The next
gate follows completed offline composition of upstream profiler PR #4 merge
`15717eae2630e80c11b113ccaeb3422871b35b40`: obtain review for an optional
KV-recovery plus communication/specialty profile, add CPU whole-chain runtime
validation, resolve the pinned scheduler compatibility hazard, and pass a
version-aware READY preflight. Historical checkpoint
`9f1464b8d017ef48e66b8b4c9bd4a5a37fdc563d` remains immutable; continue from
`feature/kv-recovery-integration` rather than repeating that reconciliation.

The checked-in hook-enabled NPU6 artifacts remain useful contaminated
development evidence: the smoke pair has complete historical chains and a
small-workload smoke delta observed once per mode. They are not primary
blind-localization cases and do not prove M0. P1 should extend the existing
hook/export path; formal controlled-live scoring additionally requires fresh
opaque cases and frozen graph-mode specialty targets.
