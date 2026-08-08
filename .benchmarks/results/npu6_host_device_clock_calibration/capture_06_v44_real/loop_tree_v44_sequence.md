# Loop Tree (v2)

- db: `PROF_000001_20260808111514183_01863898PPCAEOOK`
- source_db: `.benchmarks/results/npu6_host_device_clock_calibration/capture_06_v44_real/profile/PROF_000001_20260808111514183_01863898PPCAEOOK/msprof_20260808111521.db`
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
- scale: `1.000003514537`
- offset_ns: `-3126.909102`
- intercept_ns: `-6277622974386.856920`
- drift_ppm: `3.514537`
- profiler_to_marker_scale: `1.000020577028`
- profiler_to_marker_drift_ppm: `20.577028`
- input_marker_count: `21`
- inlier_marker_count: `21`
- rejected_marker_count: `0`
- fit_marker_count: `17`
- validation_marker_count: `4`
- absolute_residual_p50_ns: `1517.605441`
- absolute_residual_p95_ns: `4744.139285`
- absolute_residual_max_ns: `4744.139285`
- bracket_uncertainty_p95_ns: `47725.185692`
- host_clock_absolute_residual_p50_ns: `319.139675`
- host_clock_absolute_residual_p95_ns: `895.569639`
- host_clock_absolute_residual_max_ns: `895.569639`
- host_clock_uncertainty_p95_ns: `895.554358`
- profiler_to_caller_bracket_uncertainty_p95_ns: `17644.698939`
- composed_absolute_residual_p50_ns: `20379.301110`
- composed_absolute_residual_p95_ns: `26538.197787`
- composed_absolute_residual_max_ns: `26538.197787`
- direct_overlap_marker_count: `0`
- ordinal_affine_fallback_marker_count: `21`
- epsilon_ns: `71010`

- visible_productive_idle_us: `304000`
- visible_productive_idle_ns: `303999600`
- directly_explained_us: `0.24` (`0%`)
- directly_explained_ns: `240`
- correlated_explained_us: `0.00` (`0.00%`)
- correlated_explained_ns: `0`
- residual_visible_productive_idle_ns: `303999360`
- semantic_boundary: gaps in profiler-visible productive work; not proof of hardware idleness or causality

| Category | Slices | Duration (ns) | Duration (us) | Gap % |
| --- | ---: | ---: | ---: | ---: |
| `runtime_control_present` | 12 | 240 | 0.24 | 0% |
| `unattributed_visible_idle` | 43 | 303999360 | 303999 | 100% |

### Anchor-Prelude Attribution

- attributed_visible_productive_idle_us: `207749` (`68.34%`)
- attributed_visible_productive_idle_ns: `207748820`
- device_only_unassigned_us: `96251`
- device_only_unassigned_ns: `96250780`
- attribution_boundary: exact intersections with the disjoint prelude window before each anchor; device-only residual is not forced onto a node
- hierarchy_boundary: parent and child hotspot rows overlap by construction and are not additive

| Node | Kind | Total (us) | Avg (us) | Wait | Capture | Runtime | Queue delay | Host sync | No work | Unattributed |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `node-N001` Seq | `seq` | 207749 | 207749 | 0.00 | 0.00 | 0.24 | 0.00 | 0.00 | 0.00 | 207749 |
| `node-N002` Rep x24 | `repeat` | 207749 | 8656 | 0.00 | 0.00 | 0.24 | 0.00 | 0.00 | 0.00 | 207749 |
| `node-N003` MatMul | `atom` | 207749 | 8656 | 0.00 | 0.00 | 0.24 | 0.00 | 0.00 | 0.00 | 207749 |

## Root

```
tree                                              cat             |  occ   total_us    avg_us  avg_idle  avg_aux avg_self
------------------------------------------------  --------------  | ---- ---------- --------- --------- -------- --------
N001 Seq                                                          |    1     207880    207880    207749     0.24     0.00
  N002 Rep x24                                                    |    1     207880      8662      8656     0.01     0.00
    N003 MatMul                                   exec            |   24     207880      8662      8656     0.01     5.47
```
