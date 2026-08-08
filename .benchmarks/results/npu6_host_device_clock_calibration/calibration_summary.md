# NPU6 Host→Device Clock Calibration

- evidence_label: `real-online v4.4 calibration-chain repeated capture`
- capture_count: `3`
- acceptance_status: `PASS`

## Per-capture models

| Capture | Status/audit | Drift ppm marker→device / profiler→caller | Markers input/inlier/rejected | Fit/validation | Forbidden direct/validated sequence | Marker→device residual p50/p95/max (ns) | Profiler→caller residual p50/p95/max (ns) | Outer bracket p95 (ns) | Record-call bracket p95 (device ns) | Composed profiler→device residual p50/p95/max (ns) | Host-clock uncertainty p95 (device ns) | Epsilon (ns) | Correlated (ns) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `capture_05_v44_real` | `calibrated/PASS` | -1.153372 / 20.757472 | 21/21/0 | 17/4 | 0/21 | 575.845202/3035.225857/3035.225857 | 99.999903/297.236293/297.236293 | 44125.449107 | 15270.482387 | 20525.822095/25343.963834/25343.963834 | 297.235950 | 62729 | 0 |
| `capture_06_v44_real` | `calibrated/PASS` | -17.062140 / 20.577028 | 21/21/0 | 17/4 | 0/21 | 1517.605441/4744.139285/4744.139285 | 319.139675/895.569639/895.569639 | 47725.185692 | 17644.698939 | 20379.301110/26538.197787/26538.197787 | 895.554358 | 71010 | 0 |
| `capture_07_v44_real` | `calibrated/PASS` | 30.633661 / 21.911972 | 21/21/0 | 17/4 | 0/21 | 621.150063/1093.030934/1093.030934 | 194.159594/222.990758/222.990758 | 62167.904372 | 13510.413861 | 21449.392368/23007.653012/23007.653012 | 222.997589 | 76995 | 0 |

## Cross-clock audit counters

| Capture | Host contract | Fail-closed | Host source/API family | Queued TASK link |
| --- | ---: | ---: | ---: | ---: |
| `capture_05_v44_real` | 0 | 0 | 0 | 0 |
| `capture_06_v44_real` | 0 | 0 | 0 | 0 |
| `capture_07_v44_real` | 0 | 0 | 0 | 0 |

## Pooled marker distributions

| Metric | Count | p50 (ns) | p95 (ns) | max (ns) |
| --- | ---: | ---: | ---: | ---: |
| marker→device absolute validation residual | 12 | 811.861317 | 4744.139283 | 4744.139283 |
| profiler→caller absolute validation residual | 12 | 194.159585 | 895.569638 | 895.569638 |
| composed profiler→device absolute validation residual | 12 | 20901.006420 | 26538.197786 | 26538.197786 |
| scaled half-bracket uncertainty | 63 | 34201.547687 | 62167.904372 | 94284.891271 |
| scaled record-call half-bracket uncertainty | 63 | 12394.985704 | 17644.698939 | 29739.992563 |

The composed residual is a shared-observation diagnostic, not independent clock-correctness validation. This artifact validates the v4.4 calibration mechanism. A zero correlated duration means no E4 gap passed the robust host-evidence gate; it is not converted into a positive attribution claim.
