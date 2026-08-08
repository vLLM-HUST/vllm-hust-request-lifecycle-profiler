# NPU6 Fixed-rate Clock-marker Overhead A/B

- capture_acceptance: `PASS`
- protocol_acceptance: `PASS`
- calibration_acceptance: `PASS`
- full_idle_evidence_acceptance: `PASS`
- overhead_claim_status: `observed_single_pair_no_confidence_interval`
- offered load: `0.25 req/s`
- fixed window: `16.0 s`
- measured requests: `4`

## Matching checks

| Check | Match |
| --- | --- |
| probe_repository_revision | `yes` |
| probe_repository_clean | `yes` |
| workload_repository_revision | `yes` |
| workload_repository_clean | `yes` |
| client_command_except_runtime_endpoints | `yes` |
| fixed_request_schedule | `yes` |
| token_metrics_from_sse_token_ids | `yes` |
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
| request throughput | 0.311637 | 0.310661 | -0.000975 | -0.313% | request/s |
| output chunk throughput | 4.986185 | 4.970584 | -0.015601 | -0.313% | chunk/s |
| TTFT p50 | 122.124407 | 121.533218 | -0.591190 | -0.484% | ms |
| TTFT p95 | 126.590562 | 122.770062 | -3.820500 | -3.018% | ms |
| request latency p50 | 852.154624 | 852.282292 | 0.127668 | 0.015% | ms |
| request latency p95 | 857.466869 | 872.387846 | 14.920977 | 1.740% | ms |
| ITL p50 | 51.391090 | 52.067249 | 0.676159 | 1.316% | ms |
| ITL p95 | 54.081970 | 53.801617 | -0.280353 | -0.518% | ms |
| TPOT p50 | 48.600258 | 48.648398 | 0.048139 | 0.099% | ms |
| TPOT p95 | 48.806763 | 50.084358 | 1.277595 | 2.618% | ms |
| decode iteration duration p50 | 50.204845 | 50.909719 | 0.704874 | 1.404% | ms |
| decode iteration duration p95 | 52.746956 | 52.732668 | -0.014288 | -0.027% | ms |
| device productive time (full profiler boundary) | 1528183800.000000 | 1520092100.000000 | -8091700.000000 | -0.529% | ns |
| device productive fraction (full profiler boundary) | 0.053852 | 0.052632 | -0.001220 | -2.265% | ratio |
| raw marker brackets | 0.000000 | 108.000000 | 108.000000 | n/a | count |

## Enabled calibration and E4

Calibration is `calibrated` with 108/86/22 input/inlier/rejected markers, 69/17 fit/validation markers.
Marker→device residual p50/p95/max: 7249.045/17510.732/17510.732 ns; profiler→caller residual p50/p95/max: 1266.731/14565.260/14565.260 ns; composed profiler→device residual p50/p95/max: 45443.987/65549.022/65549.022 ns; bracket p95 91131.697 ns; host-clock uncertainty p95 14565.212 device ns; record-call bracket uncertainty p95 42300.860 device ns; epsilon 165509 ns; drift -3.320956/20.997414 ppm for the marker→device/profiler→caller legs. The composed residual is a shared-observation diagnostic, not independent validation.
Marker resolution provenance: 0 direct-overlap and 86 ordinal-affine-fallback markers.
E4 emitted 55 calibrated exact-connection slices covering 541740 ns of queued-visible-task delay; these remain diagnostic because the run-level analysis status is invalid_input (0 non-point and 119 point-event non-positive-duration TASK rows).

## Interpretation boundary

This retained real-online pair is rejected for an overhead acceptance claim because its source checkout was dirty outside the output directory and its client did not preserve token-ID arrival timestamps. The non-token deltas remain diagnostics only. Full-boundary device time also remains diagnostic while the sidecar run status is invalid_input.
