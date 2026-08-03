# Pinned Runtime/Device Compatibility Decision

- Decision: `BLOCKED`
- Review state: `owner_review_required`
- Evidence state: `NOT_M0_PROVEN`
- Runtime pin: `f229ba7cad21a4dba58681af6738a9fd947388e2`
- Device-plugin pin: `cafad89a5e103f31ea517c1edb56130578c3cd56`
- Benchmark pin: `0858cdb326e88ebaf8027966ba754da5ea800db4`

The pins remain valid source anchors, but they do not currently define one
executable issue-#134 tiering configuration. Two device-plugin specialty paths
are incompatible with the fixed runtime, while one runtime-owned tiering path
can statically avoid those known failures only under an explicit configuration
decision. No path is yet approved or startup-tested, so G1 and NPU admission
remain blocked.

## 1. Version evidence

The exact metadata differs by four upstream minor releases:

| Repository | Release | Upstream version | Upstream commit |
| --- | --- | --- | --- |
| runtime `f229ba7...` | `0.23.1` | `0.23.1rc0` | `1f486d96a17303ce8db8e02be39545b2be338446` |
| device `cafad89...` | `0.19.1` | `0.19.1rc1` | `b5fbfffe1dc29261c3c8e0778808cfffb19a95fb` |

Version distance alone is not the decision. The incompatible called
interfaces below are the decision evidence.

## 2. Hard blocker A: scheduler signature and copied behavior

Runtime contract and calls:

- `vllm/v1/core/sched/interface.py:51-80` declares
  `schedule(self, throttle_prefills: bool = False)`;
- `vllm/v1/core/sched/scheduler.py:442-453` implements that signature;
- `vllm/v1/engine/core.py:495` calls
  `self.scheduler.schedule(self._should_throttle_prefills())`;
- batch-queue `core.py:552` makes the same positional call.

Device implementation:

- `vllm_ascend/core/recompute_scheduler.py:192` declares only
  `schedule(self)`.

If that class is installed, either engine-step path supplies an extra
positional argument and can fail on its first scheduling step with
`TypeError`. The device scheduler is also a copied scheduler body that lacks
the fixed runtime's current-step and DP prefill-throttling behavior. Adding an
unused optional parameter alone would hide the immediate exception without
restoring the runtime's scheduler semantics, so it is not an acceptable fix.

### Installation conditions

- `vllm_ascend/ascend_config.py:200-201` reads
  `additional_config["recompute_scheduler_enable"]`; default is false.
- `vllm_ascend/platform.py:825-829` replaces `scheduler_config` when true.
- `vllm_ascend/core/recompute_scheduler.py:63-76` selects synchronous or
  asynchronous recompute scheduler.
- `vllm_ascend/platform.py:831-837` can later replace it with
  `SchedulerDynamicBatch` when the SLO option is enabled.

The known signature failure is avoided only when the complete resolved config
proves that neither recompute scheduler nor another incompatible override is
installed. A default value in source is insufficient for a formal run;
resolved parameters and a startup/interface test are required.

## 3. Hard blocker B: device NPU offload API generation

Device module `vllm_ascend/kv_offload/npu.py:16` imports:

```text
vllm.v1.kv_offload.worker.worker.OffloadingHandler
```

That module does not exist in runtime `f229ba7...`; importing the device NPU
spec module fails before a spec can be constructed.

The mismatch continues after import:

- device `npu.py:70-84` and `vllm_ascend/kv_offload/cpu_npu.py:82-124` use the
  old `OffloadingHandler/get_handlers` API;
- runtime `vllm/v1/kv_offload/base.py:509-538` and
  `vllm/v1/kv_offload/cpu/spec.py:131-150` require
  `OffloadingWorker/submit_load/submit_store/get_worker`;
- device `npu.py:105-128` constructs the old `SharedOffloadRegion` with
  `total_size_bytes` and `num_workers`;
- runtime `vllm/v1/kv_offload/cpu/shared_offload_region.py:41-48` instead
  requires `num_blocks`, `rank`, `kv_bytes_per_block`, and
  `cpu_page_size`.

Consequently `NPUOffloadingSpec` and `NPUTieringOffloadingSpec` are not usable
with the fixed runtime. Bypassing the first import would only expose the next
incompatible lifecycle and constructor.

## 4. Recompute specialty path has an additional configuration mismatch

The device `RecomputeCPUOffloadConnector` preservation branch is selected by
`RecomputeScheduler._is_kv_consumer_recompute_path()` at
`vllm_ascend/core/recompute_scheduler.py:119-121`, which requires a transfer
config that is not a KV producer.

Runtime `vllm/config/kv_transfer.py:11-12,113-118` treats `kv_both` as both
producer and consumer. Thus a `kv_both + RecomputeCPUOffloadConnector`
configuration does not enter the device scheduler's recompute-consumer
preemption branch or call its preempt offload hook. This is separate from the
signature blocker.

The device documentation says the recompute scheduler is limited to
PD-disaggregated producer/consumer modes, but the audited installation path
does not contain the corresponding complete guard. Documentation and assumed
behavior cannot substitute for an executable config test.

## 5. Benchmark #134 has no frozen executable configuration

Issue #134 fixes Qwen2.5-14B-Instruct, FP16, one 910B2, max model length 32768,
1 RPS, 8/16/24/32 GiB, three workloads, and a fixed-8-GiB comparison of
tiering disabled, tiering enabled, and HBM-only. It does not name a connector
class, spec module, scheduler override, exact byte value, or complete resolved
server configuration.

At benchmark commit `0858cdb...`, the nearest registered specialty target is:

- `official-ascend-jan-2026-v0.18.0-kv-tiering-prefix-online-qwen25-7b-910b2`;
- version `1.0.0`, profile `specialty`, status `provisional`;
- source-spec SHA-256
  `1c5c5dffcc15e6daae58979cbd27ff71f8ac15841ae50e2507642174a40f75a5`;
- registry SHA-256
  `2073283467797cbe4a74682249b4e40c7c5ded4ebd393392161e038dd9bdb94c`.

`src/vllm_hust_benchmark/data/official_targets.json:1825-1863`, the associated
baseline, and `official_scenarios.json:496-520` define a 7B prefix workload but
not #134's 14B, 32768 context, capacity scan, or three modes. The runner can
accept parameter JSON and include it in resolved-config hashing, but no
content-addressed #134 parameter document exists at the fixed snapshot.

### Historical PR #124 is reference-only

The checked-in historical head used:

- 7B, max model length 4608;
- device KV `268435456` bytes (256 MiB);
- `OffloadingConnector`, `kv_role=kv_both`;
- runtime-core `TieringOffloadingSpec`;
- CPU bytes `1073741824` (1 GiB);
- core `89334ef1...` and plugin `8b2adf16...`.

It is not a resolved configuration or result for #134. Its reusable design
fact is only the structural distinction between a no-connector control and a
runtime-owned OffloadingConnector tiering candidate.

## 6. Candidate-family decision matrix

| Family | Scheduler/API result | Communication result | Current decision |
| --- | --- | --- | --- |
| HBM-only, no connector, default runtime scheduler | no known selected signature conflict; produces no restore episode | `communication_mode=none` is legal under P0 when all other mode constraints hold | control candidate only; exact config still unfrozen |
| Runtime `OffloadingConnector + TieringOffloadingSpec`, device recompute scheduler explicitly false | static call path uses runtime scheduler and runtime Ascend offload worker; avoids both known device specialty blockers | D2H/H2D requires approved specialty/issue-2 profile | recommended implementation candidate, but `BLOCKED` pending profile/config approval and startup test |
| Device `NPUOffloadingSpec` or `NPUTieringOffloadingSpec` | import, worker lifecycle, and shared-region constructor incompatible | also needs non-`none` profile | `BLOCKED_INCOMPATIBLE` |
| Device `RecomputeCPUOffloadConnector + RecomputeScheduler` | scheduler signature/body incompatible; `kv_both` does not select expected recovery hook | also needs non-`none` profile | `BLOCKED_INCOMPATIBLE` |

The runtime-owned candidate is a static compatibility finding, not a runtime
GO. It still needs a frozen resolved config, import/interface CPU coverage, a
real startup smoke after later admission, and the approved communication
profile.

## 7. Recommended G0 resolution

The smallest path that preserves the approved source anchors is:

1. freeze the recovery-profile bytes with Remygred, then produce a separate
   content-addressed H2D/D2H/wait mapping with a complete subtype/edge roster
   and obtain issue-2-authority approval for that artifact; neither digest nor
   approval substitutes for the other;
2. create a separate content-addressed issue-#134 configuration candidate that
   explicitly selects runtime-core `TieringOffloadingSpec`, contains no device
   `spec_module_path`, and fixes
   `recompute_scheduler_enable=false`;
3. define tiering-disabled and HBM-only as mutually exclusive resolved
   configurations rather than labels for the same command;
4. identify exactly one copy-optimization switch, or mark that comparison
   unsupported;
5. run CPU/import/interface tests before any runtime source edit or NPU
   preflight; and
6. preserve the current pins until either those tests pass or a replacement
   pair is explicitly approved.

This resolution does not use the incompatible device specialty classes. If
the intended research question specifically requires their recompute behavior,
choose one of these larger alternatives instead:

- port the device scheduler to the complete runtime scheduler interface and
  behavior, port the device offload implementation to
  `OffloadingWorker/get_worker`, add failure/lifecycle tests, record new file
  digests, and approve the compatibility patch; or
- select a device-plugin commit aligned with runtime 0.23.1, redo the complete
  pair audit, and approve a new paired SHA.

Merely adding an optional scheduler argument or suppressing an import is not a
valid compatibility patch.

## 8. Required pre-G1 CPU checks

Before source instrumentation, an approved candidate needs tests that:

- assert the selected scheduler callable accepts the runtime call shape in
  ordinary and batch-queue paths;
- resolve `OffloadingConnector` and the exact spec from the full configuration
  without importing `vllm_ascend.kv_offload.npu`;
- assert `recompute_scheduler_enable=false` after platform configuration;
- construct scheduler/worker connector metadata with fake KV cache objects;
- preserve request, recovery epoch, job, logical block, rank, direction, and
  process identity across a fake successful H2D handoff;
- reject missing/duplicate completion, retry/failure, changed blocks, and an
  incomplete expected-process receipt; and
- exercise tracing disabled and enabled without producer-path I/O or serving
  exceptions.

Only after those checks and explicit owner decisions may the status move from
`BLOCKED` to a limited CPU-integration GO. NPU READY remains a later,
read-only, version-aware preflight gate.
