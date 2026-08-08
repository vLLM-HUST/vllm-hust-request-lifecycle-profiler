# Host→Device Clock Calibration Runbook

Status: three new `real-online` NPU6 captures validate the v4.4
profiler-host→caller-clock→device mechanism using distinct record-call and
record-through-synchronize brackets, plus the strengthened SQL audit. A new
v4.4 fixed-rate marker OFF/ON pair closes the workload-specific single-pair
overhead measurement. No v4.4 serving capture has yet produced accepted
positive host attribution; the prior serving replay used the superseded
observation definition and is retracted.

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

The collector uses `time.time_ns()` (`CLOCK_REALTIME`) immediately before and
after `aclrtRecordEvent`, then once more immediately after
`aclrtSynchronizeEvent`. It writes the
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
   non-empty overlap with the narrow
   `[host_before_ns, record_after_ns)` bracket;
2. a non-negative profiler connectionId on that API row; and
3. at most one TASK with that connectionId on the requested device and, when
   supplied, stream.

The outer `[host_before_ns, host_after_ns]` bracket includes synchronization
and is never used to train the profiler→caller leg. Non-empty overlap is used
because real NPU6 measurements show clock skew
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
       scale, offset_ns, intercept_ns, drift_ppm, profiler_to_marker_scale,
       profiler_to_marker_drift_ppm,
       profiler_caller_observation_kind, marker_device_observation_kind,
       input_marker_count, inlier_marker_count, rejected_marker_count,
       fit_marker_count, validation_marker_count,
       absolute_residual_p50_ns, absolute_residual_p95_ns,
       absolute_residual_max_ns, bracket_uncertainty_p95_ns,
       host_clock_absolute_residual_p50_ns,
       host_clock_absolute_residual_p95_ns,
       host_clock_absolute_residual_max_ns,
       host_clock_uncertainty_p95_ns,
       profiler_to_caller_bracket_uncertainty_p95_ns,
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
msprof CANN_API timestamp. `g` pairs the profiled `aclrtRecordEvent` midpoint
with the narrow caller record-call midpoint; `f` pairs the outer
record-through-synchronize midpoint with device TASK ns. Both legs use the
deterministic fit/holdout split. Final epsilon is the marker→device p95
residual, outer half-bracket p95, first-leg p95 residual converted into device
ns, and narrow record-call half-bracket p95. The composed residual is reported
only as a shared-observation diagnostic and cannot replace this four-term sum.
`offset_ns` is the reference-coordinate delta; `intercept_ns` is the separate
affine intercept.

Only `alignment_status=calibrated` with `has_profiler_host_mapping=1` from real
markers permits a real-trace cross-clock claim. `uncalibrated` and `invalid`
retain host rows and structural links but compute no temporal overlap or delay.
`synthetic_only` validates the mechanism only.

Official host evidence is deliberately narrower than possible evidence:

- host synchronization: robust interval
  `[F(profiler_start)+epsilon, F(profiler_end)-epsilon)` intersected with a visible
  gap;
- enqueue delay: unique exact connectionId plus robust interval
  `[F(profiler_end)+epsilon, task_start)` intersected with a visible gap.

Possible-only overlap and non-robust delay are materialized in
`traceloom_idle_candidate`; they never replace an E4 slice. Device evidence
keeps priority over correlated host evidence. Run
`docs/report-sql/idle-evidence-audit.sql` and require `audit_status=PASS` for
every reported run.

## 4. Recorded NPU6 evidence

Three independent v4.4 micro-captures under
`.benchmarks/results/npu6_host_device_clock_calibration/` exercise the real
Python collector → narrow record-call bracket → `aclrtRecordEvent` → profiler
CANN_API/TASK → TSV resolver → composed-clock Theil–Sen chain.
`capture_05_v44_real` through `capture_07_v44_real` each contain 21/21 inlier
markers, 17 fit markers, 4 validation markers, zero rejected markers, 21
`direct_overlap` resolutions, zero ordinal fallbacks, and `audit_status=PASS`.
The third capture also has `analysis_status=ok`; all three have zero correlated
duration because the micro workload supplies no E4 robust host-overlap or delay
slice.

| Capture | marker→device p50/p95/max (ns) | profiler→caller p50/p95/max (ns) | outer bracket p95 (ns) | record bracket p95 (device ns) | composed p50/p95/max (ns) | epsilon (ns) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| capture 05 | 575.845 / 3035.226 / 3035.226 | 100.000 / 297.236 / 297.236 | 44125.449 | 15270.482 | 20525.822 / 25343.964 / 25343.964 | 62729 |
| capture 06 | 1517.605 / 4744.139 / 4744.139 | 319.140 / 895.570 / 895.570 | 47725.186 | 17644.699 | 20379.301 / 26538.198 / 26538.198 | 71010 |
| capture 07 | 621.150 / 1093.031 / 1093.031 | 194.160 / 222.991 / 222.991 | 62167.904 | 13510.414 | 21449.392 / 23007.653 / 23007.653 | 76995 |

The pooled 12-marker marker→device validation residual distribution is
p50/p95/max 811.861/4744.139/4744.139 ns; profiler→caller is
194.160/895.570/895.570 ns. The composed diagnostic is
20901.006/26538.198/26538.198 ns: unlike the superseded shared-midpoint model,
it exposes rather than cancels record→device latency. Across 63 markers, the
outer and narrow scaled half-bracket p95 values are 62167.904 and 17644.699 ns.
The structured outputs are `calibration_summary.json` and
`calibration_summary.md`; acceptance requires three unique v4.4 run IDs,
correct observation kinds, four-term epsilon equality, and three passing SQL
audits. The structured report expands the four cross-clock counters for every
capture: `host_explanation_contract_errors`,
`cross_clock_fail_closed_errors`, `host_evidence_source_errors`, and
`queued_task_link_errors`; all four are zero in all three captures.

The earlier fixed-rate serving sidecars and the reported 1133→1 slice change
were produced before the v4.4 observation amendment. They lack
`record_after_ns`, still encode the superseded first-leg correspondence, and
MUST NOT be used as current cross-clock evidence. Their matched workload
measurements remain historical diagnostics only. Because v4.4 adds one runtime
timestamp read per marker, the marker OFF/ON A/B and any serving E4 claim must
be recollected. A positive serving claim additionally requires
`analysis_status=ok`.

An additional `--task-time=l2` probe under
`.benchmarks/results/npu6_clock_marker_l2_validity_probe/` still contains 84
zero-duration kernel/memcpy tasks (plus 650 point events). Increasing the
profiler task-time level does not close this source-validity blocker.

The superseded pre-v4.4 marker-overhead report remains at
`.benchmarks/results/npu6_clock_marker_overhead_fixed_rate_ab/report/` and is
historical only. The current report is
`.benchmarks/results/npu6_clock_marker_overhead_v44_fixed_rate_ab/`. Both new
variants use the same model, fixed request schedule, seed, 2 req/s offered
load, 24 s window, workload/server configuration, profiler options, and msprof
boundary; the distinct loopback ports only isolate the two sequential server
processes. Each completes 48/48 requests. The disabled run emits zero markers;
the enabled run emits 587 successful new-format brackets and calibrates 565
inliers (453 fit, 112 validation, 22 rejected) with epsilon 164088 ns. Both SQL
audits pass.

Enabled-minus-disabled changes request throughput by -0.297%, TTFT p50/p95 by
-1.416%/+1.472%, request-latency p50/p95 by +2.046%/+2.093%, ITL p50/p95 by
+2.002%/+2.477%, TPOT p50/p95 by +1.973%/+2.179%, and decode-iteration
p50/p95 by +1.869%/+2.812%. Full-boundary device productive time changes by
-0.261%, but that device metric and the three emitted exact-connection E4
slices are diagnostic: both source profiles contain non-point non-positive
duration TASK rows and therefore have `analysis_status=invalid_input`. The
structured result is `protocol_acceptance=PASS`,
`calibration_acceptance=PASS`, and `capture_acceptance=PARTIAL`. This is one
workload-specific matched pair, not a confidence interval, universal overhead
bound, graph-mode result, or CPU/host-memory/NPU-HBM measurement.

## 5. Evidence boundary

The deterministic fixtures remain `simulation/model`/contract evidence. The
captures above support the `real-online` claim that the v4.4 composed
calibration mechanism executes on NPU6 profiler data with auditable uncertainty.
The matched pair additionally measures host-visible v4.4 marker overhead for
one eager-mode workload. It does not provide an accepted positive E4 serving
capture, a confidence interval, or a device-overhead acceptance result. None of
these results proves causality or establishes graph-mode behavior.
