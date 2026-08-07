# Loop Tree (v2)

- db: `PROF_000001_20260807125153693_01655972DMDPEJFR`
- source_db: `/workspace/ascend-b2-pilot/src/vllm-request-lifecycle-profiler-plugin/.benchmarks/results/npu6_host_device_clock_calibration/capture_04_real_calibrated/profile/PROF_000001_20260807125153693_01655972DMDPEJFR/msprof_20260807125201.db`
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
- attribution_rule_version: `host_device_projection_v1`
- alignment_status: `calibrated`

### Host→Device Clock Calibration

- scale: `1.000017031092`
- drift_ppm: `17.031092`
- input_marker_count: `21`
- inlier_marker_count: `21`
- rejected_marker_count: `0`
- fit_marker_count: `17`
- validation_marker_count: `4`
- absolute_residual_p50_ns: `214.626539`
- absolute_residual_p95_ns: `3630.587859`
- absolute_residual_max_ns: `3630.587859`
- bracket_uncertainty_p95_ns: `49381.341004`
- epsilon_ns: `53012`

- visible_productive_idle_us: `294449`
- visible_productive_idle_ns: `294448580`
- directly_explained_us: `0.2` (`0%`)
- directly_explained_ns: `200`
- correlated_explained_us: `0.00` (`0.00%`)
- correlated_explained_ns: `0`
- residual_visible_productive_idle_ns: `294448380`
- semantic_boundary: gaps in profiler-visible productive work; not proof of hardware idleness or causality

| Category | Slices | Duration (ns) | Duration (us) | Gap % |
| --- | ---: | ---: | ---: | ---: |
| `runtime_control_present` | 10 | 200 | 0.2 | 0% |
| `unattributed_visible_idle` | 41 | 294448380 | 294448 | 100% |

### Anchor-Prelude Attribution

- attributed_visible_productive_idle_us: `208033` (`70.65%`)
- attributed_visible_productive_idle_ns: `208033000`
- device_only_unassigned_us: `86416`
- device_only_unassigned_ns: `86415580`
- attribution_boundary: exact intersections with the disjoint prelude window before each anchor; device-only residual is not forced onto a node
- hierarchy_boundary: parent and child hotspot rows overlap by construction and are not additive

| Node | Kind | Total (us) | Avg (us) | Wait | Capture | Runtime | Queue delay | Host sync | No work | Unattributed |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `node-N001` Seq | `seq` | 208033 | 208033 | 0.00 | 0.00 | 0.2 | 0.00 | 0.00 | 0.00 | 208033 |
| `node-N002` Rep x24 | `repeat` | 208033 | 8668 | 0.00 | 0.00 | 0.2 | 0.00 | 0.00 | 0.00 | 208033 |
| `node-N003` MatMul | `atom` | 208033 | 8668 | 0.00 | 0.00 | 0.2 | 0.00 | 0.00 | 0.00 | 208033 |

## Root

```
tree                                              cat             |  occ   total_us    avg_us  avg_idle  avg_aux avg_self
------------------------------------------------  --------------  | ---- ---------- --------- --------- -------- --------
N001 Seq                                                          |    1     208165    208165    208033      0.2     0.00
  N002 Rep x24                                                    |    1     208165      8674      8668     0.01     0.00
    N003 MatMul                                   exec            |   24     208165      8674      8668     0.01      5.5
```
