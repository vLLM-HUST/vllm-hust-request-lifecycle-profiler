# NPU6 Host→Device Clock Calibration

- evidence_label: `real-online calibration-chain repeated capture`
- capture_count: `3`
- acceptance_status: `PASS`

## Per-capture models

| Capture | Status/audit | Drift ppm | Markers input/inlier/rejected | Fit/validation | Residual p50/p95/max (ns) | Bracket p95 (ns) | Epsilon (ns) | Correlated (ns) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `capture_02_real_calibrated` | `calibrated/PASS` | 17.638930 | 21/21/0 | 17/4 | 2232.080899/3257.739760/3257.739760 | 53096.436548 | 56355 | 0 |
| `capture_03_real_calibrated` | `calibrated/PASS` | 20.967414 | 21/21/0 | 17/4 | 2980.759819/14091.348543/14091.348543 | 47896.504245 | 61988 | 0 |
| `capture_04_real_calibrated` | `calibrated/PASS` | 17.031092 | 21/21/0 | 17/4 | 214.626539/3630.587859/3630.587859 | 49381.341004 | 53012 | 0 |

## Pooled marker distributions

| Metric | Count | p50 (ns) | p95 (ns) | max (ns) |
| --- | ---: | ---: | ---: | ---: |
| absolute validation residual | 12 | 2232.080894 | 14091.348500 | 14091.348500 |
| scaled half-bracket uncertainty | 63 | 40686.217649 | 53096.436548 | 97373.541629 |

This artifact validates calibration quality. A zero correlated duration means no E4 gap passed the robust host-evidence gate; it is not converted into a positive attribution claim.
