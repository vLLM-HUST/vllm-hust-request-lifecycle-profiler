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
| request throughput | 0.311285 | 0.311249 | -0.000036 | -0.011% | request/s |
| output chunk throughput | 4.980559 | 4.979990 | -0.000569 | -0.011% | chunk/s |
| TTFT p50 | 122.530558 | 118.535182 | -3.995376 | -3.261% | ms |
| TTFT p95 | 125.640187 | 119.684271 | -5.955916 | -4.740% | ms |
| request latency p50 | 851.651710 | 823.193870 | -28.457840 | -3.341% | ms |
| request latency p95 | 866.878739 | 848.155493 | -18.723246 | -2.160% | ms |
| ITL p50 | 51.819455 | 49.966763 | -1.852692 | -3.575% | ms |
| ITL p95 | 54.871302 | 52.039881 | -2.831422 | -5.160% | ms |
| TPOT p50 | 48.527835 | 46.998838 | -1.528998 | -3.151% | ms |
| TPOT p95 | 49.516652 | 48.578952 | -0.937700 | -1.894% | ms |
| decode iteration duration p50 | 50.425602 | 49.543564 | -0.882038 | -1.749% | ms |
| decode iteration duration p95 | 52.199282 | 51.035589 | -1.163694 | -2.229% | ms |
| device productive time (full profiler boundary) | 1525755360.000000 | 1520226180.000000 | -5529180.000000 | -0.362% | ns |
| device productive fraction (full profiler boundary) | 0.055064 | 0.052195 | -0.002869 | -5.211% | ratio |
| raw marker brackets | 0.000000 | 108.000000 | 108.000000 | n/a | count |

## Enabled calibration and E4

Calibration is `calibrated` with 108/87/21 input/inlier/rejected markers, 70/17 fit/validation markers.
Marker→device residual p50/p95/max: 8331.446/30692.740/30692.740 ns; profiler→caller residual p50/p95/max: 2976.414/35461.322/35461.322 ns; composed profiler→device residual p50/p95/max: 45509.814/93077.393/93077.393 ns; bracket p95 105966.556 ns; host-clock uncertainty p95 35461.174 device ns; record-call bracket uncertainty p95 40680.830 device ns; epsilon 212802 ns; drift -4.186365/21.529720 ppm for the marker→device/profiler→caller legs. The composed residual is a shared-observation diagnostic, not independent validation.
Marker resolution provenance: 0 direct-overlap and 87 ordinal-affine-fallback markers.
E4 emitted 60 calibrated exact-connection slices covering 2835462 ns of queued-visible-task delay; these remain diagnostic because the run-level analysis status is invalid_input (0 non-point and 105 point-event non-positive-duration TASK rows).

## Interpretation boundary

This retained real-online pair is rejected for an overhead acceptance claim because its source checkout was dirty outside the output directory and its client did not preserve token-ID arrival timestamps. The non-token deltas remain diagnostics only. Full-boundary device time also remains diagnostic while the sidecar run status is invalid_input.
