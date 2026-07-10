# Experiment Plan

## Phase 0: Trace Schema Validation

- Unit-test lifecycle event ordering, missing stages, and bottleneck
  attribution rules.
- Generate synthetic traces for known queueing, prefill, decode, streaming, and
  cleanup bottlenecks.

Evidence label: `simulation/model`.

## Phase 1: Existing-Server Probe on NPU6

- Instrument baseline serving without changing runtime behavior.
- Run shared workloads and emit per-request timelines.
- Compare profiler reports against raw logs and simple stage timers.

Evidence label: `existing-server-probe`.

## Phase 2: Controlled Fault Injection

- Inject long-prompt surge, decode-heavy output, slow streaming client, and KV
  pressure conditions.
- Measure whether attribution matches injected ground truth.

Evidence label: `real-online` only when the runtime actually serves requests on
NPU6; otherwise use `replay` or `simulation/model`.

## Required Artifact Fields

Every run directory must include `run_metadata.json` with parent commit,
environment, NPU id, model, runtime, workload source, injected fault, command,
dirty state, and evidence label.

