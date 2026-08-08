# Loop Tree (v2)

- db: `PROF_000001_20260808111408927_01861962RFGMIPIJ`
- source_db: `.benchmarks/results/npu6_host_device_clock_calibration/capture_05_v44_real/profile/PROF_000001_20260808111408927_01861962RFGMIPIJ/msprof_20260808111416.db`
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

- analysis_status: `invalid_input`
- collection_status: `unknown`
- attribution_rule_version: `host_device_projection_v2`
- alignment_status: `calibrated`

### Host→Device Clock Calibration

- source_clock_domain: `profiler_host`
- intermediate_clock_domain: `caller_clock_realtime`
- mapping_kind: `composed_affine`
- profiler_caller_observation_kind: `record_api_midpoint_to_record_bracket_midpoint`
- marker_device_observation_kind: `record_sync_bracket_midpoint_to_task_start`
- scale: `1.000019604075`
- offset_ns: `-8492.659773`
- intercept_ns: `-35016557124869.414585`
- drift_ppm: `19.604075`
- profiler_to_marker_scale: `1.000020757472`
- profiler_to_marker_drift_ppm: `20.757472`
- input_marker_count: `21`
- inlier_marker_count: `21`
- rejected_marker_count: `0`
- fit_marker_count: `17`
- validation_marker_count: `4`
- absolute_residual_p50_ns: `575.845202`
- absolute_residual_p95_ns: `3035.225857`
- absolute_residual_max_ns: `3035.225857`
- bracket_uncertainty_p95_ns: `44125.449107`
- host_clock_absolute_residual_p50_ns: `99.999903`
- host_clock_absolute_residual_p95_ns: `297.236293`
- host_clock_absolute_residual_max_ns: `297.236293`
- host_clock_uncertainty_p95_ns: `297.235950`
- profiler_to_caller_bracket_uncertainty_p95_ns: `15270.482387`
- composed_absolute_residual_p50_ns: `20525.822095`
- composed_absolute_residual_p95_ns: `25343.963834`
- composed_absolute_residual_max_ns: `25343.963834`
- direct_overlap_marker_count: `0`
- ordinal_affine_fallback_marker_count: `21`
- epsilon_ns: `62729`

- visible_productive_idle_us: `321484`
- visible_productive_idle_ns: `321484100`
- directly_explained_us: `0.18` (`0%`)
- directly_explained_ns: `180`
- correlated_explained_us: `0.00` (`0.00%`)
- correlated_explained_ns: `0`
- residual_visible_productive_idle_ns: `321483920`
- semantic_boundary: gaps in profiler-visible productive work; not proof of hardware idleness or causality

| Category | Slices | Duration (ns) | Duration (us) | Gap % |
| --- | ---: | ---: | ---: | ---: |
| `runtime_control_present` | 9 | 180 | 0.18 | 0% |
| `unattributed_visible_idle` | 40 | 321483920 | 321484 | 100% |

### Anchor-Prelude Attribution

- attributed_visible_productive_idle_us: `207736` (`64.62%`)
- attributed_visible_productive_idle_ns: `207736140`
- device_only_unassigned_us: `113748`
- device_only_unassigned_ns: `113747960`
- attribution_boundary: exact intersections with the disjoint prelude window before each anchor; device-only residual is not forced onto a node
- hierarchy_boundary: parent and child hotspot rows overlap by construction and are not additive

| Node | Kind | Total (us) | Avg (us) | Wait | Capture | Runtime | Queue delay | Host sync | No work | Unattributed |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `node-N001` Seq | `seq` | 207736 | 207736 | 0.00 | 0.00 | 0.18 | 0.00 | 0.00 | 0.00 | 207736 |
| `node-N002` Rep x24 | `repeat` | 207736 | 8656 | 0.00 | 0.00 | 0.18 | 0.00 | 0.00 | 0.00 | 207736 |
| `node-N003` MatMul | `atom` | 207736 | 8656 | 0.00 | 0.00 | 0.18 | 0.00 | 0.00 | 0.00 | 207736 |

## Root

```
tree                                              cat             |  occ   total_us    avg_us  avg_idle  avg_aux avg_self
------------------------------------------------  --------------  | ---- ---------- --------- --------- -------- --------
N001 Seq                                                          |    1     207868    207868    207736     0.18     0.00
  N002 Rep x24                                                    |    1     207868      8661      8656     0.01     0.00
    N003 MatMul                                   exec            |   24     207868      8661      8656     0.01     5.51
```
