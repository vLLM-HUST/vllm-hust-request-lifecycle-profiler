# Loop Tree (v2)

- db: `PROF_000001_20260808111531951_01864298RFOJABQC`
- source_db: `/workspace/ascend-b2-pilot/src/vllm-request-lifecycle-profiler-plugin/.benchmarks/results/npu6_host_device_clock_calibration/capture_07_v44_real/profile/PROF_000001_20260808111531951_01864298RFOJABQC/msprof_20260808111539.db`
- device_id: `6`
- stream_scope: `device_compute_sequence`
- db_idx: `0`
- global_rank: `native`
- report_view: `native_report_tree`
- renderer: `native_loop_tree_markdown_v0`
- source_kind: `ascend_sqlite_hot_path`
- trace_event_count: `54`
- anchor_count: `24`

## Visible Productive Idle Evidence

- analysis_status: `ok`
- collection_status: `unknown`
- attribution_rule_version: `host_device_projection_v2`
- alignment_status: `calibrated`

### Host→Device Clock Calibration

- source_clock_domain: `profiler_host`
- intermediate_clock_domain: `caller_clock_realtime`
- mapping_kind: `composed_affine`
- profiler_caller_observation_kind: `record_api_midpoint_to_record_bracket_midpoint`
- marker_device_observation_kind: `record_sync_bracket_midpoint_to_task_start`
- scale: `1.000052546304`
- offset_ns: `-7243.170103`
- intercept_ns: `-93857564441394.322181`
- drift_ppm: `52.546304`
- profiler_to_marker_scale: `1.000021911972`
- profiler_to_marker_drift_ppm: `21.911972`
- input_marker_count: `21`
- inlier_marker_count: `21`
- rejected_marker_count: `0`
- fit_marker_count: `17`
- validation_marker_count: `4`
- absolute_residual_p50_ns: `621.150063`
- absolute_residual_p95_ns: `1093.030934`
- absolute_residual_max_ns: `1093.030934`
- bracket_uncertainty_p95_ns: `62167.904372`
- host_clock_absolute_residual_p50_ns: `194.159594`
- host_clock_absolute_residual_p95_ns: `222.990758`
- host_clock_absolute_residual_max_ns: `222.990758`
- host_clock_uncertainty_p95_ns: `222.997589`
- profiler_to_caller_bracket_uncertainty_p95_ns: `13510.413861`
- composed_absolute_residual_p50_ns: `21449.392368`
- composed_absolute_residual_p95_ns: `23007.653012`
- composed_absolute_residual_max_ns: `23007.653012`
- direct_overlap_marker_count: `21`
- ordinal_affine_fallback_marker_count: `0`
- epsilon_ns: `76995`

- visible_productive_idle_us: `344373`
- visible_productive_idle_ns: `344373400`
- directly_explained_us: `0.22` (`0%`)
- directly_explained_ns: `220`
- correlated_explained_us: `0.00` (`0.00%`)
- correlated_explained_ns: `0`
- residual_visible_productive_idle_ns: `344373180`
- semantic_boundary: gaps in profiler-visible productive work; not proof of hardware idleness or causality

| Category | Slices | Duration (ns) | Duration (us) | Gap % |
| --- | ---: | ---: | ---: | ---: |
| `runtime_control_present` | 11 | 220 | 0.22 | 0% |
| `unattributed_visible_idle` | 42 | 344373180 | 344373 | 100% |

### Anchor-Prelude Attribution

- attributed_visible_productive_idle_us: `207668` (`60.3%`)
- attributed_visible_productive_idle_ns: `207667540`
- device_only_unassigned_us: `136706`
- device_only_unassigned_ns: `136705860`
- attribution_boundary: exact intersections with the disjoint prelude window before each anchor; device-only residual is not forced onto a node
- hierarchy_boundary: parent and child hotspot rows overlap by construction and are not additive

| Node | Kind | Total (us) | Avg (us) | Wait | Capture | Runtime | Queue delay | Host sync | No work | Unattributed |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `node-N001` Seq | `seq` | 207668 | 207668 | 0.00 | 0.00 | 0.22 | 0.00 | 0.00 | 0.00 | 207667 |
| `node-N002` Rep x24 | `repeat` | 207668 | 8653 | 0.00 | 0.00 | 0.22 | 0.00 | 0.00 | 0.00 | 207667 |
| `node-N003` MatMul | `atom` | 207668 | 8653 | 0.00 | 0.00 | 0.22 | 0.00 | 0.00 | 0.00 | 207667 |

## Root

```
tree                                              cat             |  occ   total_us    avg_us  avg_idle  avg_aux avg_self
------------------------------------------------  --------------  | ---- ---------- --------- --------- -------- --------
N001 Seq                                                          |    1     207799    207799    207667     0.22     0.00
  N002 Rep x24                                                    |    1     207799      8658      8653     0.01     0.00
    N003 MatMul                                   exec            |   24     207799      8658      8653     0.01     5.49
```
