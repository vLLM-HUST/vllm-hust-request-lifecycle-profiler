# Repeated NPU6 clock-marker overhead A/B

- capture_acceptance: `PASS`
- protocol_acceptance: `PASS`
- full_idle_evidence_acceptance: `PASS`
- overhead_claim_status: `accepted_repeated_matched_ab`
- pair_count: `3`
- total requests per variant: `12`
- pooled correlated E4: `169` slices / `3918602` ns

| Metric | Disabled pair-mean | Enabled pair-mean | Delta | Delta % | per-pair Δ% p50 | per-pair Δ% p95 | Unit |
|---|---:|---:|---:|---:|---:|---:|---|
| request throughput | 0.311577 | 0.311066 | -0.000510 | -0.163764 | -0.166792 | -0.026969 | request/s |
| output chunk throughput | 4.985228 | 4.977064 | -0.008164 | -0.163764 | -0.166792 | -0.026969 | chunk/s |
| TTFT p50 | 122.690582 | 120.830952 | -1.859630 | -1.515707 | -0.804043 | -0.516084 | ms |
| TTFT p95 | 125.595764 | 123.718407 | -1.877357 | -1.494761 | -3.017998 | 2.692754 | ms |
| request latency p50 | 855.616708 | 844.999640 | -10.617068 | -1.240867 | -0.407978 | -0.027314 | ms |
| request latency p95 | 867.178921 | 862.809565 | -4.369356 | -0.503859 | -1.060863 | 1.460024 | ms |
| ITL p50 | 51.870036 | 51.373544 | -0.496491 | -0.957184 | -0.597220 | 1.124419 | ms |
| ITL p95 | 54.306382 | 53.585074 | -0.721308 | -1.328220 | -0.518385 | 1.528909 | ms |
| TPOT p50 | 48.800358 | 48.186875 | -0.613483 | -1.257128 | -0.729793 | 0.016167 | ms |
| TPOT p95 | 49.508899 | 49.422447 | -0.086451 | -0.174618 | -1.193647 | 2.236530 | ms |
| decode iteration duration p50 | 50.614871 | 50.437343 | -0.177529 | -0.350744 | -0.693992 | 1.194197 | ms |
| decode iteration duration p95 | 52.568614 | 52.156847 | -0.411767 | -0.783295 | -0.108644 | -0.035244 | ms |
| device productive time (full profiler boundary) | 1527207966.666667 | 1519727600.000000 | -7480366.666667 | -0.489807 | -0.529498 | -0.379100 | ns |
| device productive fraction (full profiler boundary) | 0.056981 | 0.053252 | -0.003729 | -6.543958 | -5.211176 | -2.559576 | ratio |
| raw marker brackets | 0.000000 | 108.000000 | 108.000000 | n/a | n/a | n/a | count |
