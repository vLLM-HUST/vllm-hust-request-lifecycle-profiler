# NPU6 Host→Device Clock Calibration

- evidence_label: `real-online calibration-chain repeated capture`
- capture_count: `3`
- acceptance_status: `PASS`

## Per-capture models

| Capture | Status/audit | Drift ppm marker→device / profiler→marker | Markers input/inlier/rejected | Fit/validation | Direct/fallback | Marker→device residual p50/p95/max (ns) | Profiler→marker residual p50/p95/max (ns) | Bracket p95 (ns) | Composed profiler→device residual p50/p95/max (ns) | Host-clock uncertainty p95 (device ns) | Epsilon (ns) | Correlated (ns) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `capture_02_real_calibrated` | `calibrated/PASS` | 17.638930 / -9.549596 | 21/21/0 | 17/4 | 21/0 | 2232.080899/3257.739760/3257.739760 | 3214.014320/5857.865546/5857.865546 | 53096.436548 | 2903.807005/3625.887973/3625.887973 | 5857.968873 | 62213 | 0 |
| `capture_03_real_calibrated` | `calibrated/PASS` | 20.967414 / -2.202660 | 21/21/0 | 17/4 | 21/0 | 2980.759819/14091.348543/14091.348543 | 4029.976476/11472.362784/11472.362784 | 47896.504245 | 574.864921/3885.128482/3885.128482 | 11472.603330 | 73461 | 0 |
| `capture_04_real_calibrated` | `calibrated/PASS` | 17.031092 / -4.609161 | 21/21/0 | 17/4 | 21/0 | 214.626539/3630.587859/3630.587859 | 1027.567084/4500.925993/4500.925993 | 49381.341004 | 870.414789/2412.330843/2412.330843 | 4501.002648 | 57513 | 0 |

## Pooled marker distributions

| Metric | Count | p50 (ns) | p95 (ns) | max (ns) |
| --- | ---: | ---: | ---: | ---: |
| marker→device absolute validation residual | 12 | 2232.080894 | 14091.348500 | 14091.348500 |
| profiler→marker absolute validation residual | 12 | 3214.014321 | 11472.362757 | 11472.362757 |
| composed profiler→device absolute validation residual | 12 | 977.126494 | 3885.128483 | 3885.128483 |
| scaled half-bracket uncertainty | 63 | 40686.217649 | 53096.436548 | 97373.541629 |

This artifact validates calibration quality. A zero correlated duration means no E4 gap passed the robust host-evidence gate; it is not converted into a positive attribution claim.
