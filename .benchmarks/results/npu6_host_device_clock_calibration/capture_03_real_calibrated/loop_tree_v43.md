# Loop Tree (v2)

- db: `PROF_000001_20260807125135481_01655572RIQCMDCF`
- source_db: `/workspace/ascend-b2-pilot/src/vllm-request-lifecycle-profiler-plugin/.benchmarks/results/npu6_host_device_clock_calibration/capture_03_real_calibrated/profile/PROF_000001_20260807125135481_01655572RIQCMDCF/msprof_20260807125143.db`
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
- attribution_rule_version: `host_device_projection_v1`
- alignment_status: `calibrated`

### Host→Device Clock Calibration

- scale: `1.000020967414`
- drift_ppm: `20.967414`
- input_marker_count: `21`
- inlier_marker_count: `21`
- rejected_marker_count: `0`
- fit_marker_count: `17`
- validation_marker_count: `4`
- absolute_residual_p50_ns: `2980.759819`
- absolute_residual_p95_ns: `14091.348543`
- absolute_residual_max_ns: `14091.348543`
- bracket_uncertainty_p95_ns: `47896.504245`
- epsilon_ns: `61988`

- visible_productive_idle_us: `297214`
- visible_productive_idle_ns: `297213520`
- directly_explained_us: `0.24` (`0%`)
- directly_explained_ns: `240`
- correlated_explained_us: `0.00` (`0.00%`)
- correlated_explained_ns: `0`
- residual_visible_productive_idle_ns: `297213280`
- semantic_boundary: gaps in profiler-visible productive work; not proof of hardware idleness or causality

| Category | Slices | Duration (ns) | Duration (us) | Gap % |
| --- | ---: | ---: | ---: | ---: |
| `runtime_control_present` | 12 | 240 | 0.24 | 0% |
| `unattributed_visible_idle` | 43 | 297213280 | 297213 | 100% |

### Anchor-Prelude Attribution

- attributed_visible_productive_idle_us: `207133` (`69.69%`)
- attributed_visible_productive_idle_ns: `207133180`
- device_only_unassigned_us: `90080`
- device_only_unassigned_ns: `90080340`
- attribution_boundary: exact intersections with the disjoint prelude window before each anchor; device-only residual is not forced onto a node
- hierarchy_boundary: parent and child hotspot rows overlap by construction and are not additive

| Node | Kind | Total (us) | Avg (us) | Wait | Capture | Runtime | Queue delay | Host sync | No work | Unattributed |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `node-N001` Seq | `seq` | 207133 | 207133 | 0.00 | 0.00 | 0.24 | 0.00 | 0.00 | 0.00 | 207133 |
| `node-N002` Rep x24 | `repeat` | 207133 | 8631 | 0.00 | 0.00 | 0.24 | 0.00 | 0.00 | 0.00 | 207133 |
| `node-N003` MatMul | `atom` | 207133 | 8631 | 0.00 | 0.00 | 0.24 | 0.00 | 0.00 | 0.00 | 207133 |

## Root

```
tree                                              cat             |  occ   total_us    avg_us  avg_idle  avg_aux avg_self
------------------------------------------------  --------------  | ---- ---------- --------- --------- -------- --------
N001 Seq                                                          |    1     207264    207264    207133     0.24     0.00
  N002 Rep x24                                                    |    1     207264      8636      8631     0.01     0.00
    N003 MatMul                                   exec            |   24     207264      8636      8631     0.01     5.44
```
