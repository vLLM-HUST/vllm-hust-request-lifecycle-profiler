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
| client_command_except_runtime_endpoints | `yes` |
| fixed_request_schedule | `yes` |
| installed_runtime | `yes` |
| model | `yes` |
| profiler_boundary | `yes` |
| profiler_options | `yes` |
| request_shape | `yes` |
| server_command_except_runtime_endpoint | `yes` |
| workload_commit | `yes` |

## Observed enabled - disabled deltas

| Metric | Disabled | Enabled | Delta | Delta % | Unit |
| --- | ---: | ---: | ---: | ---: | --- |
| request throughput | 1.901548 | 1.895892 | -0.005656 | -0.297% | request/s |
| output chunk throughput | 60.849536 | 60.668552 | -0.180984 | -0.297% | chunk/s |
| TTFT p50 | 158.314018 | 156.072326 | -2.241692 | -1.416% | ms |
| TTFT p95 | 177.473602 | 180.086643 | 2.613041 | 1.472% | ms |
| request latency p50 | 1861.839578 | 1899.930720 | 38.091141 | 2.046% | ms |
| request latency p95 | 1898.446925 | 1938.189141 | 39.742216 | 2.093% | ms |
| ITL p50 | 55.060203 | 56.162734 | 1.102531 | 2.002% | ms |
| ITL p95 | 57.149218 | 58.564566 | 1.415348 | 2.477% | ms |
| TPOT p50 | 55.301750 | 56.393086 | 1.091335 | 1.973% | ms |
| TPOT p95 | 55.714712 | 56.928576 | 1.213864 | 2.179% | ms |
| decode iteration duration p50 | 53.487357 | 54.486846 | 0.999489 | 1.869% | ms |
| decode iteration duration p95 | 55.144610 | 56.695090 | 1.550480 | 2.812% | ms |
| device productive time (full profiler boundary) | 7827852900.000000 | 7807413120.000000 | -20439780.000000 | -0.261% | ns |
| device productive fraction (full profiler boundary) | 0.157495 | 0.156522 | -0.000973 | -0.618% | ratio |
| raw marker brackets | 0.000000 | 587.000000 | 587.000000 | n/a | count |

## Enabled calibration and E4

Calibration is `calibrated` with 587/565/22 input/inlier/rejected markers, 453/112 fit/validation markers.
Marker→device residual p50/p95/max: 5454.265/17828.917/40536.033 ns; profiler→caller residual p50/p95/max: 4572.241/8015.858/15615.260 ns; composed profiler→device residual p50/p95/max: 45575.887/48462.832/53874.593 ns; bracket p95 97626.750 ns; host-clock uncertainty p95 8015.838 device ns; record-call bracket uncertainty p95 40615.896 device ns; epsilon 164088 ns; drift -2.562059/19.769207 ppm for the marker→device/profiler→caller legs. The composed residual is a shared-observation diagnostic, not independent validation.
Marker resolution provenance: 0 direct-overlap and 565 ordinal-affine-fallback markers.
E4 emitted 3 calibrated exact-connection slices covering 141344 ns of queued-visible-task delay; these remain diagnostic because the run-level analysis status is invalid_input (107 non-point and 659 point-event non-positive-duration TASK rows).

## Interpretation boundary

This is a real-online, fixed-rate matched pair. It reports the observed latency and iteration perturbation for this workload; it does not establish a population confidence interval or a universal overhead bound. Full-boundary device time includes server warm-up and profiler-tail effects and is diagnostic while the sidecar run status is invalid_input.
