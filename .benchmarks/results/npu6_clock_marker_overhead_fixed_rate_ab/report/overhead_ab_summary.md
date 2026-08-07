# NPU6 Fixed-rate Clock-marker Overhead A/B

- capture_acceptance: `PARTIAL`
- protocol_acceptance: `PASS`
- calibration_acceptance: `PASS`
- full_idle_evidence_acceptance: `FAIL`
- overhead_claim_status: `observed_single_pair_no_confidence_interval`
- offered load: `2.0 req/s`
- fixed window: `24.0 s`
- measured requests: `48`

## Matching checks

| Check | Match |
| --- | --- |
| client_command_except_output | `yes` |
| fixed_request_schedule | `yes` |
| installed_runtime | `yes` |
| model | `yes` |
| profiler_boundary | `yes` |
| profiler_options | `yes` |
| request_shape | `yes` |
| server_command | `yes` |
| workload_commit | `yes` |

## Observed enabled - disabled deltas

| Metric | Disabled | Enabled | Delta | Delta % | Unit |
| --- | ---: | ---: | ---: | ---: | --- |
| request throughput | 1.897931 | 1.898225 | 0.000294 | 0.015% | request/s |
| output chunk throughput | 60.733779 | 60.743188 | 0.009409 | 0.015% | chunk/s |
| TTFT p50 | 160.496671 | 157.329793 | -3.166878 | -1.973% | ms |
| TTFT p95 | 177.657553 | 179.421172 | 1.763619 | 0.993% | ms |
| request latency p50 | 1869.441959 | 1902.127659 | 32.685700 | 1.748% | ms |
| request latency p95 | 1898.444046 | 1933.414995 | 34.970948 | 1.842% | ms |
| ITL p50 | 54.888999 | 56.143231 | 1.254232 | 2.285% | ms |
| ITL p95 | 57.236407 | 58.217073 | 0.980666 | 1.713% | ms |
| TPOT p50 | 55.115332 | 56.343396 | 1.228064 | 2.228% | ms |
| TPOT p95 | 55.614097 | 56.710835 | 1.096738 | 1.972% | ms |
| decode iteration duration p50 | 53.192828 | 54.557839 | 1.365011 | 2.566% | ms |
| decode iteration duration p95 | 55.193832 | 56.216922 | 1.023090 | 1.854% | ms |
| device productive time (full profiler boundary) | 7814890120.000000 | 7855211560.000000 | 40321440.000000 | 0.516% | ns |
| device productive fraction (full profiler boundary) | 0.157542 | 0.159224 | 0.001682 | 1.068% | ratio |
| raw marker brackets | 0.000000 | 587.000000 | 587.000000 | n/a | count |

## Enabled calibration and E4

Calibration is `calibrated` with 587/565/22 input/inlier/rejected markers, 453/112 fit/validation markers.
Residual p50/p95/max: 8329.205/23831.788/43889.346 ns; bracket p95 107876.729 ns; epsilon 131709 ns; drift -2.513645 ppm.
E4 emitted 1133 calibrated exact-connection slices covering 61776173 ns of queued-visible-task delay; these remain diagnostic because the run-level analysis status is invalid_input (126 non-point and 678 point-event non-positive-duration TASK rows).

## Interpretation boundary

This is a real-online, fixed-rate matched pair. It measures an observed ~1–2% latency/iteration perturbation for this workload; it does not establish a population confidence interval or a universal overhead bound. Full-boundary device time includes server warm-up and profiler-tail effects and is diagnostic while the sidecar run status is invalid_input.

## Excluded diagnostics

The retained diagnostic capture(s) are excluded from official deltas because their batching/queueing state was not reproduced.
