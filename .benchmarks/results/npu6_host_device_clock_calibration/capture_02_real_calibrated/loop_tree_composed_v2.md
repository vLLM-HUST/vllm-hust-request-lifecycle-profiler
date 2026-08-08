# Loop Tree (v2)

- db: `PROF_000001_20260807124600000_01649898LMMGPPMG`
- source_db: `/workspace/ascend-b2-pilot/src/vllm-request-lifecycle-profiler-plugin/.benchmarks/results/npu6_host_device_clock_calibration/capture_02_real_calibrated/profile/PROF_000001_20260807124600000_01649898LMMGPPMG/msprof_20260807124606.db`
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

- source_clock_domain: `profiler_host`
- intermediate_clock_domain: `caller_clock_realtime`
- mapping_kind: `composed_affine`
- scale: `1.000008089165`
- drift_ppm: `8.089165`
- profiler_to_marker_scale: `0.999990450404`
- profiler_to_marker_drift_ppm: `-9.549596`
- input_marker_count: `21`
- inlier_marker_count: `21`
- rejected_marker_count: `0`
- fit_marker_count: `17`
- validation_marker_count: `4`
- absolute_residual_p50_ns: `2232.080899`
- absolute_residual_p95_ns: `3257.739760`
- absolute_residual_max_ns: `3257.739760`
- bracket_uncertainty_p95_ns: `53096.436548`
- host_clock_absolute_residual_p50_ns: `3214.014320`
- host_clock_absolute_residual_p95_ns: `5857.865546`
- host_clock_absolute_residual_max_ns: `5857.865546`
- host_clock_uncertainty_p95_ns: `5857.968873`
- composed_absolute_residual_p50_ns: `2903.807005`
- composed_absolute_residual_p95_ns: `3625.887973`
- composed_absolute_residual_max_ns: `3625.887973`
- direct_overlap_marker_count: `21`
- ordinal_affine_fallback_marker_count: `0`
- epsilon_ns: `62213`

- visible_productive_idle_us: `292936`
- visible_productive_idle_ns: `292935620`
- directly_explained_us: `0.2` (`0%`)
- directly_explained_ns: `200`
- correlated_explained_us: `0.00` (`0.00%`)
- correlated_explained_ns: `0`
- residual_visible_productive_idle_ns: `292935420`
- semantic_boundary: gaps in profiler-visible productive work; not proof of hardware idleness or causality

| Category | Slices | Duration (ns) | Duration (us) | Gap % |
| --- | ---: | ---: | ---: | ---: |
| `runtime_control_present` | 10 | 200 | 0.2 | 0% |
| `unattributed_visible_idle` | 41 | 292935420 | 292935 | 100% |

### Anchor-Prelude Attribution

- attributed_visible_productive_idle_us: `207588` (`70.86%`)
- attributed_visible_productive_idle_ns: `207587840`
- device_only_unassigned_us: `85348`
- device_only_unassigned_ns: `85347780`
- attribution_boundary: exact intersections with the disjoint prelude window before each anchor; device-only residual is not forced onto a node
- hierarchy_boundary: parent and child hotspot rows overlap by construction and are not additive

| Node | Kind | Total (us) | Avg (us) | Wait | Capture | Runtime | Queue delay | Host sync | No work | Unattributed |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `node-N001` Seq | `seq` | 207588 | 207588 | 0.00 | 0.00 | 0.2 | 0.00 | 0.00 | 0.00 | 207588 |
| `node-N002` Rep x24 | `repeat` | 207588 | 8649 | 0.00 | 0.00 | 0.2 | 0.00 | 0.00 | 0.00 | 207588 |
| `node-N003` MatMul | `atom` | 207588 | 8649 | 0.00 | 0.00 | 0.2 | 0.00 | 0.00 | 0.00 | 207588 |

## Root

```
tree                                              cat             |  occ   total_us    avg_us  avg_idle  avg_aux avg_self
------------------------------------------------  --------------  | ---- ---------- --------- --------- -------- --------
N001 Seq                                                          |    1     207720    207720    207588      0.2     0.00
  N002 Rep x24                                                    |    1     207720      8655      8649     0.01     0.00
    N003 MatMul                                   exec            |   24     207720      8655      8649     0.01     5.52
```
