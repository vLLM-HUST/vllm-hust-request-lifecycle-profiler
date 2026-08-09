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
| client_command_except_runtime_endpoints | `yes` |
| fixed_request_schedule | `yes` |
| installed_runtime | `yes` |
| model | `yes` |
| probe_repository_clean | `yes` |
| probe_repository_revision | `yes` |
| profiler_boundary | `yes` |
| profiler_options | `yes` |
| request_shape | `yes` |
| server_command_except_runtime_endpoint | `yes` |
| sidecar_attribution_rule_version | `yes` |
| sidecar_contract_version | `yes` |
| token_metrics_from_sse_token_ids | `yes` |
| workload_commit | `yes` |
| workload_repository_clean | `yes` |
| workload_repository_revision | `yes` |

## Observed enabled - disabled deltas

| Metric | Disabled | Enabled | Delta | Delta % | Unit |
| --- | ---: | ---: | ---: | ---: | --- |
| request throughput | 0.311809 | 0.311289 | -0.000520 | -0.167% | request/s |
| output chunk throughput | 4.988940 | 4.980618 | -0.008321 | -0.167% | chunk/s |
| TTFT p50 | 123.416781 | 122.424457 | -0.992324 | -0.804% | ms |
| TTFT p95 | 124.556542 | 128.700888 | 4.144347 | 3.327% | ms |
| request latency p50 | 863.043790 | 859.522758 | -3.521033 | -0.408% | ms |
| request latency p95 | 877.191155 | 867.885356 | -9.305799 | -1.061% | ms |
| ITL p50 | 52.399562 | 52.086622 | -0.312941 | -0.597% | ms |
| ITL p95 | 53.965875 | 54.913724 | 0.947849 | 1.756% | ms |
| TPOT p50 | 49.272981 | 48.913390 | -0.359591 | -0.730% | ms |
| TPOT p95 | 50.203281 | 49.604031 | -0.599250 | -1.194% | ms |
| decode iteration duration p50 | 51.214168 | 50.858745 | -0.355422 | -0.694% | ms |
| decode iteration duration p95 | 52.759604 | 52.702284 | -0.057320 | -0.109% | ms |
| device productive time (full profiler boundary) | 1527684740.000000 | 1518864520.000000 | -8820220.000000 | -0.577% | ns |
| device productive fraction (full profiler boundary) | 0.062027 | 0.054929 | -0.007097 | -11.442% | ratio |
| raw marker brackets | 0.000000 | 108.000000 | 108.000000 | n/a | count |

## Enabled calibration and E4

Calibration is `calibrated` with 108/86/22 input/inlier/rejected markers, 69/17 fit/validation markers.
Marker→device residual p50/p95/max: 9830.919/48789.492/48789.492 ns; profiler→caller residual p50/p95/max: 2432.800/24127.905/24127.905 ns; composed profiler→device residual p50/p95/max: 49217.234/79190.223/79190.223 ns; bracket p95 117652.145 ns; host-clock uncertainty p95 24127.832 device ns; record-call bracket uncertainty p95 50986.346 device ns; epsilon 241556 ns; drift -3.020968/20.916825 ppm for the marker→device/profiler→caller legs. The composed residual is a shared-observation diagnostic, not independent validation.
Marker resolution provenance: 0 direct-overlap and 86 ordinal-affine-fallback markers.
E4 emitted 54 accepted calibrated exact-connection slices covering 541400 ns of queued-visible-task delay. Both variant analysis statuses are `ok`; protocol and calibration gates pass; and the enabled source contains 0 non-point invalid-duration TASK rows. Its 108 non-positive-duration point observations remain legal points, not invalid intervals.

## Interpretation boundary

This real-online pair passes capture, protocol, calibration, and full idle-evidence acceptance and is an accepted input to the repeated matched A/B aggregate. Its standalone overhead status remains `observed_single_pair_no_confidence_interval`; it does not establish a population, high-load, graph-mode, or memory/HBM overhead bound.
