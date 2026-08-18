# Scheduler profiler PR-I2 runtime hooks

Status: implementation candidate

PR-I2 connects the PR-I1 bounded exporter to the call sites audited by PR-I0.
It targets only upstream vLLM commit
`ad7125a431e176d4161099480a66f0169609a690` with vLLM-Ascend commit
`80610e4438dba05011b05f89fc45d91e96992671`. It does not activate collection,
run an NPU experiment, compose a TraceLoom database, or establish a performance
or device-idle claim.

## Implementation boundary

The parent package owns runtime-profile admission, process-local lifecycle
identity reuse, cycle/batch/step pairing, clock-bridge sampling, and formal
evidence invalidation. The vLLM overlay is deliberately thin and contains only
the audited call-site observations:

- adapter initialization after the executor, KV caches, scheduler, and batch
  queue capacity have resolved, but before request admission;
- cycle start immediately inside `Scheduler.schedule` and cycle end after
  `_update_after_schedule`;
- fixed-cardinality token-budget observations for running, waiting, and
  skipped-waiting gates;
- active-sequence-cap observations at the waiting-queue gate;
- aggregate prefill/decode token splits for the retained `SchedulerOutput`;
- original request-level sampling cardinality capture before AsyncLLM expands
  parallel samples, with EngineCore admission restricted to `n=1`;
- dispatch immediately before synchronous `execute_model` and final result
  after `Future.result` plus any synchronous `sample_tokens`; and
- exporter close at `EngineCore.shutdown`.

The adapter retains the required empty-control batch and execution step when
zero tokens are scheduled. It uses the scheduler output object's process-local
identity only to pair the already-audited schedule and execution boundaries;
that value is not written to the wire and is not a cross-profile identity.

## Runtime admission

Enabling the path still does not guarantee activation. Before opening a shard,
the parent adapter requires the exact audited runtime and device commits and
the complete `vllm-0.21-uniproc-sync-one-device-v1` profile: synchronous
scheduling, one in-flight batch, UniProc, eager decoder-only generation,
world-size one, no speculative decoding, no multimodal mode, no KV/EC transfer
connector, and lifecycle communication mode `none`.

The request-level `n=1` condition is dynamic rather than an engine setting.
When profiling is enabled, the audited AsyncLLM path carries the original
sampling cardinality across child-request expansion; scheduler admission
permanently invalidates formal evidence if the marker is absent, malformed, or
not one. Serving remains unaffected.

Unsupported or malformed profiles create no scheduler shard. With a valid
profile, hook and pairing failures remain serving-fail-open but permanently
invalidate formal evidence. A successful writer close is still insufficient:
Route B admission additionally requires a valid exact-C1 scheduler validation
receipt.

## Activation variables

The experiment launcher supplies all values before EngineCore starts:

```bash
export VLLM_RLP_SCHEDULER_PROFILE_PATH=/run/profile/scheduler
export VLLM_RLP_EXPERIMENT_RUN_ID=<opaque-run-id>
export VLLM_RLP_SERVER_INSTANCE_ID=<opaque-server-id>
export VLLM_RLP_SCHEDULER_SHARD_ID=<scheduler-shard-id>
export VLLM_RLP_PROCESS_INSTANCE_ID=<32-lowercase-hex-process-id>
export VLLM_RLP_CLOCK_DOMAIN_ID=<32-lowercase-hex-clock-domain>
export VLLM_RLP_PROFILER_PARENT_COMMIT=<40-lowercase-hex-commit>
export VLLM_RLP_RUNTIME_CORE_COMMIT=ad7125a431e176d4161099480a66f0169609a690
export VLLM_RLP_DEVICE_PLUGIN_COMMIT=80610e4438dba05011b05f89fc45d91e96992671
export VLLM_RLP_COMMUNICATION_MODE=none
# PR-I6 only: optional non-wire writer diagnostics, absolute and fresh.
export VLLM_RLP_SCHEDULER_DIAGNOSTICS_PATH=/run/profile/scheduler-runtime-diagnostics.json
```

`process_instance_id` is opaque in the scheduler contract. The current
lifecycle wire also uses it as `process_uuid`, so simultaneous lifecycle and
scheduler collection uses the lifecycle wire's narrower 32-lowercase-hex
representation. Both streams then record the same process and clock-domain
identity while retaining independent files, sequences, writers, and summaries.

The optional diagnostics path is separate from both frozen streams. After an
immutable successful scheduler close it publishes a mode-`0600` JSON sidecar
binding the completed shard SHA-256 and reporting maximum writer service gap,
queued bytes, and queued records. It exists for PR-I6 overhead qualification;
omitting the variable creates no sidecar, and publication failures remain
serving-fail-open while I6 evidence fails closed.

## Audited runtime carrier

The repository does not modify the newer historical runtime gitlink. Instead,
the deterministic carrier validates the exact PR-I0 source hashes before
producing the three small call-site edits and the hook shim:

```bash
python scripts/apply_scheduler_profile_i2_runtime.py \
  --runtime-source /path/to/vllm-ad7125a \
  --apply
```

The command refuses a source mismatch before writing. Without `--apply` it is
a read-only compatibility check and prints the resulting file hashes.

After an immutable successful close, generate the separate Route-B receipt:

```bash
python scripts/verify_scheduler_profile_contract.py \
  --scheduler-shard /run/profile/scheduler.rlp-scheduler.SH0.jsonl \
  --write-receipt /run/profile/scheduler-validation.json \
  --json
```

## CPU validation

```bash
VLLM_SCHEDULER_I2_SRC=/path/to/vllm-ad7125a \
PYTHONPATH=src python -B -m pytest -q \
  tests/test_scheduler_profile_contract.py \
  tests/test_scheduler_profile_exporter.py \
  tests/test_scheduler_profile_runtime.py \
  tests/test_runtime_hooks.py \
  tests/test_plugin.py
```

These tests cover exact source compatibility and compilation, supported and
unsupported admission, default-off behavior, shared lifecycle identity,
constraint capture, cycle/batch/step emission, fail-closed pairing, writer
close, and exact-C1 receipt validation. They are CPU implementation evidence,
not runtime activation or scientific evidence.
