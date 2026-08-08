# Host→Device Clock Calibration Runbook

Status: repeated `real-online` NPU6 captures now validate the complete
profiler-host→caller-clock→device composed calibration and the strengthened SQL
audit. A serving replay exercises the corrected E4 path but remains diagnostic
because its source has `analysis_status=invalid_input`.

This runbook connects the parent profiler's Ascend marker collector to
TraceLoom's calibrated host-evidence continuation after E1–E4. Its central
safety rule is simple: `aclrtEventGetTimestamp` returns raw device syscnt and
must not be treated as the profiler TASK nanosecond domain.

## 1. Collect host brackets in the profiled process

Enable the bracket output path:

```bash
export VLLM_RLP_ASCEND_CLOCK_MARKER_BRACKETS_PATH=/path/to/clock_marker_brackets.tsv
```

At a runtime hook site that already has the target Ascend context and stream,
create one collector and reuse its timeline event:

```python
from vllm_request_lifecycle_profiler import AscendClockMarkerCollector

collector = AscendClockMarkerCollector.from_env(
    device_id=6,
    stream_handle=native_aclrt_stream_pointer,
    stream_id=profiler_stream_id_if_known,
)
if collector is not None:
    collector.record()  # repeat at well-spaced points throughout the run
```

The collector uses `time.time_ns()` (`CLOCK_REALTIME`) immediately before
`aclrtRecordEvent` and immediately after `aclrtSynchronizeEvent`. It writes the
host PID/native TID, device, optional profiler stream id, call site, and return
status. It does not initialize or switch the caller's device/context. Close it
before runtime teardown.

Collect at least 6 successful markers; use 11 or more well-spaced markers per
device so the deterministic every-fifth holdout contains multiple points.
Run at least three repeated captures as required by the idle-evidence
contract. The same `msprof` capture must include both CANN_API and TASK rows
from the process that wrote the brackets.

## 2. Resolve and analyze

Use the matching single-device profile and bracket file:

```bash
traceloom /path/to/PROF_... \
  --clock-marker-brackets /path/to/clock_marker_brackets.tsv \
  --compat-db-out /path/to/report.traceloom.db \
  --timings
```

For every successful bracket, TraceLoom requires:

1. a unique same-PID/TID `aclrtRecordEvent` identity, normally by exactly one
   non-empty overlap with the host bracket;
2. a non-negative profiler connectionId on that API row; and
3. at most one TASK with that connectionId on the requested device and, when
   supplied, stream.

Non-empty overlap is used because real NPU6 measurements show clock skew
between profiler host API timestamps and the caller's `CLOCK_REALTIME`
bracket. In longer captures the skew can remove direct overlap. The only
fallback is a strict order-preserving bijection: the successful-bracket count
must equal the same-thread `aclrtRecordEvent` count, both timestamp sequences
must be strictly increasing, and after an endpoint-affine correction each API
must have its same-ordinal bracket as the unique nearest bracket. Any
extra/missing API, nearest-neighbor tie, non-affine sequence, or overlap
ambiguity still fails closed. The matched `TASK.startNs` becomes
`device_timestamp_ns`. A uniquely identified API with no connectionId, or a
connectionId with no matching TASK, remains an auditable rejected marker and
cannot enter the fit. This handles a profiler device-data horizon that ends
before its flushed host-API tail. Multiple matching APIs or TASKs are still a
fatal ambiguity. Failed runtime calls also remain rejected marker rows.
Ordinal fallback requires at least two pairs on the same thread; one distant
bracket plus one API cannot identify an affine relation even when six such
singletons exist across a device. Every resolved row retains its matched
CANN_API interval, `direct_overlap`/`ordinal_affine_fallback` method, and
fallback residual. The direct 11-field `--clock-markers` input lacks this
profiler-host interval and is therefore restricted to controlled fixtures with
`--clock-markers-synthetic`.

## 3. Acceptance checks

Inspect the sidecar before using any host-derived explanation:

```sql
select device_id, alignment_status, source_clock_domain,
       intermediate_clock_domain, mapping_kind,
       scale, drift_ppm, profiler_to_marker_scale,
       profiler_to_marker_drift_ppm,
       input_marker_count, inlier_marker_count, rejected_marker_count,
       fit_marker_count, validation_marker_count,
       absolute_residual_p50_ns, absolute_residual_p95_ns,
       absolute_residual_max_ns, bracket_uncertainty_p95_ns,
       host_clock_absolute_residual_p50_ns,
       host_clock_absolute_residual_p95_ns,
       host_clock_absolute_residual_max_ns,
       host_clock_uncertainty_p95_ns,
       composed_absolute_residual_p50_ns,
       composed_absolute_residual_p95_ns,
       composed_absolute_residual_max_ns, epsilon_ns
from traceloom_clock_model;

select marker_state, resolution_method, count(*),
       max(resolution_residual_ns)
from traceloom_clock_marker
group by marker_state, resolution_method;

select link_status, count(*)
from traceloom_task_api_link
group by link_status;

select category, evidence_relation, sum(duration_ns)
from traceloom_idle_explanation
group by category, evidence_relation;
```

The fitted mapping is the explicit composition `F(p)=f(g(p))`, where `p` is an
msprof CANN_API timestamp, `g` maps msprof-host→caller `CLOCK_REALTIME`, and `f`
maps caller `CLOCK_REALTIME`→device TASK ns. Both legs use the deterministic
fit/holdout split. Final epsilon is marker→device p95 residual plus scaled
bracket p95 plus the first-leg p95 residual converted into device ns.

Only `alignment_status=calibrated` with `has_profiler_host_mapping=1` from real
markers permits a real-trace cross-clock claim. `uncalibrated` and `invalid`
retain host rows and structural links but compute no temporal overlap or delay.
`synthetic_only` validates the mechanism only.

Official host evidence is deliberately narrower than possible evidence:

- host synchronization: robust interval
  `[f(host_start)+epsilon, f(host_end)-epsilon)` intersected with a visible
  gap;
- enqueue delay: unique exact connectionId plus robust interval
  `[f(host_end)+epsilon, task_start)` intersected with a visible gap.

Possible-only overlap and non-robust delay are materialized in
`traceloom_idle_candidate`; they never replace an E4 slice. Device evidence
keeps priority over correlated host evidence. Run
`docs/report-sql/idle-evidence-audit.sql` and require `audit_status=PASS` for
every reported run.

## 4. Recorded NPU6 evidence

Three independent micro-captures under
`.benchmarks/results/npu6_host_device_clock_calibration/` exercise the real
Python collector → `aclrtRecordEvent` → profiler CANN_API/TASK → TSV resolver →
composed-clock Theil–Sen chain. `capture_02_real_calibrated` through
`capture_04_real_calibrated` each contain 21/21 inlier markers, 17 fit markers,
4 validation markers, zero rejected markers, 21 `direct_overlap` resolutions,
zero ordinal fallbacks, and `audit_status=PASS` under the expanded audit.

| Capture | marker→device p50/p95/max (ns) | profiler→caller p50/p95/max (ns) | composed p50/p95/max (ns) | host uncertainty (device ns) | epsilon (ns) |
| --- | ---: | ---: | ---: | ---: | ---: |
| capture 02 | 2232.081 / 3257.740 / 3257.740 | 3214.014 / 5857.866 / 5857.866 | 2903.807 / 3625.888 / 3625.888 | 5857.969 | 62213 |
| capture 03 | 2980.760 / 14091.349 / 14091.349 | 4029.976 / 11472.363 / 11472.363 | 574.865 / 3885.128 / 3885.128 | 11472.603 | 73461 |
| capture 04 | 214.627 / 3630.588 / 3630.588 | 1027.567 / 4500.926 / 4500.926 | 870.415 / 2412.331 / 2412.331 | 4501.003 | 57513 |

The pooled 12-marker marker→device validation residual distribution is
p50/p95/max 2232.081/14091.349/14091.349 ns. The profiler→caller distribution is
3214.014/11472.363/11472.363 ns, and the composed profiler→device distribution
is 977.126/3885.128/3885.128 ns. The pooled scaled half-bracket distribution
over 63 markers is p50/p95/max 40686.218/53096.437/97373.542 ns. The structured
outputs are `calibration_summary.json` and `calibration_summary.md` in that
directory; acceptance requires three unique run IDs, composed calibrated
models, and three passing expanded SQL audits.

The fixed-rate serving capture under
`.benchmarks/results/npu6_clock_marker_overhead_fixed_rate_ab/marker_enabled/`
resolves 565 of 587
markers; 22 profiler-tail markers after the device TASK horizon remain rejected.
The model uses 453 fit and 112 validation markers. Marker→device residual
p50/p95/max is 8329.205/23831.788/43889.346 ns; profiler→caller residual is
7940.634/23558.420/44835.814 ns; composed profiler→device residual is
935.058/4083.598/9511.218 ns; bracket p95 is 107876.729 ns and the corrected
epsilon is 155267 ns. The old analyzer materialized 1133
`exact_connection_id` `queued_visible_task_delay` slices covering 61,776,173
ns, but it applied a caller-clock-trained model directly to msprof host API
timestamps. Those rows are retracted as cross-clock evidence; the old audit did
not contain cross-clock invariants. The composed replay retains one 93407 ns
queued-delay slice, with zero errors in all four cross-clock audit counters. In
addition, run-level
`analysis_status=invalid_input`: the profiler contains 126 zero-duration
kernel/memcpy tasks in addition to 678 ignored zero-duration point events, so
the E3 observed-universe scan is incomplete. The remaining E4 row therefore
demonstrates the corrected runtime path but is diagnostic rather than accepted
localization; a valid-status serving capture is still required.

An additional `--task-time=l2` probe under
`.benchmarks/results/npu6_clock_marker_l2_validity_probe/` still contains 84
zero-duration kernel/memcpy tasks (plus 650 point events). Increasing the
profiler task-time level does not close this source-validity blocker.

The matched marker-overhead report is
`.benchmarks/results/npu6_clock_marker_overhead_fixed_rate_ab/report/`.
Both variants use the same model, fixed request schedule, seed, 2 req/s offered
load, 24 s window, server command, and msprof boundary; each completes 48/48
requests. Enabled-minus-disabled changes request throughput by +0.015%, TTFT
p95 by +0.993%, latency p95 by +1.842%, ITL p95 by +1.713%, TPOT p95 by
+1.972%, decode-iteration p95 by +1.854%, and full-boundary device productive
time by +0.516%. The client and host-iteration metrics establish a
workload-specific observed perturbation; the full-boundary device metric stays
diagnostic while the sidecar run status is invalid. This is a single matched
pair without a confidence interval, not a universal overhead bound.

## 5. Evidence boundary

The deterministic fixtures remain `simulation/model`/contract evidence. The
captures above support the `real-online` claim that composed cross-clock
calibration works on NPU6 profiler data. The serving replay executes corrected
host attribution, but `analysis_status=invalid_input` prevents a valid full-run
claim. None of these results proves causality, establishes graph-mode behavior,
or justifies overhead claims beyond the recorded workload and pair.
