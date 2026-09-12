# Issue #1 blind-attribution pilot result

Status: `PILOT_REVEALED_NOT_M0_PROVEN`

This document records the first local real-online attribution pilot after all
Team-B method results were locked. It is an ordinary evidence summary, not an
approval, co-signature, content-freeze, or digest-chain artifact.

## Target and evidence class

- Evidence class: `real-online` runtime service evidence.
- Device: one Ascend 910B2, TP1.
- Model: `Qwen/Qwen2.5-14B-Instruct`, revision
  `cf98f3b3bbb457ad9e2bb7baf9a0125b6b88caa8`.
- Runtime: `vllm-hust` `c180d643c66f7a12434ae551cfc83cd7b7795302`.
- Device plugin: `vllm-ascend-hust`
  `95f390bb7816b5d557eb327c110b801f2a5b2cf5`.
- Workload: OASST1 fixed 64, workload commit
  `76e24c85bcab76ecfabb831c9444002b6efffd58` and OASST1 projection commit
  `fdf72ae0827c1cda404aff25b6603abec9e3399b`.
- Profiler source: the pre-blind calibration source commit recorded in
  `.benchmarks/results/issue1_preblind_noise_calibration/summary.json`.
- TraceLoom source: `63e86fc5095ee2552400c8a6c2c863faeaabf0b4`.
- Configuration: bfloat16, `max_model_len=10880`, 2 GiB KV cache, eager mode,
  `OffloadingConnector`/`TieringOffloadingSpec`, 8 GiB CPU offload,
  `lifecycle_reconcile=false`.
- Fixed insufficient-evidence floor: `212845.4035560009 ms`.

Each case contains five matched AB/BA service-lifecycle pairs. The Team-B
input contained only neutral case IDs and normalized bundles. Team-A oracle
files and intervention manifests were not copied into the Team-B input.

## Revealed cases and method results

| Method | Case accuracy | Positive cases | Negative abstention |
| --- | ---: | ---: | ---: |
| Aggregate metrics | 1/3 | 0/2 | 1/1 |
| Flat stage timers | 3/3 | 2/2 | 1/1 |
| Raw normalized events | 1/3 | 0/2 | 1/1 |
| Lifecycle spans without causal ranking | 3/3 | 2/2 | 1/1 |
| Full lifecycle DAG | 3/3 | 2/2 | 1/1 |

The two positive cases both used independently generated queue/admission
interventions. The negative case had no intervention and remained below the
declared evidence floor. Every non-abstained positive result proposed the
rank-one counterfactual `queue_or_admission`.

For the three arms that expose candidate-level stage/span evidence, the
queue/admission paired deltas were:

| Neutral case | Five paired deltas (ms) | Median (ms) | IQR (ms) | Bootstrap 95% interval (ms) | Top-1 selection |
| --- | --- | ---: | ---: | --- | ---: |
| `case-01` | 1101484.61, 1384168.89, 1039817.90, 1214838.65, 1032023.07 | 1101484.61 | 175020.74 | [1032023.07, 1384168.89] | 1.0 |
| `case-02` | 1092627.79, 1460144.79, 1012806.91, 1234131.70, 1026179.19 | 1092627.79 | 207952.50 | [1012806.91, 1460144.79] | 1.0 |

The negative case had no positive candidate surviving the floor/dominance
rules. Its measured medians were approximately `-1.56 ms` for communication,
`-3954.92 ms` for decode, and `-7782.40 ms` for queue/admission; all methods
therefore abstained.

## Interpretation and limits

The pilot shows that the lifecycle span and DAG views can localize the
controlled queue/admission effect while abstaining on the no-intervention
case. Aggregate metrics and raw event rows do not expose enough candidate-level
structure and therefore abstain on the positive cases.

This is not a general accuracy claim, a production root-cause claim, or a
performance result. Both positive cases use the same controlled mechanism, so
mechanism diversity has not been tested. The generated bundles contain no
TraceLoom device-backed links; the reported localization is based on the
host-monotonic runtime observation seam and must not be described as device
causality.

The communication case `c02b` is excluded because a 60-second H2D intervention
caused runtime `serialization_failure` before a complete treatment result was
written. It is invalid evidence, not a communication diagnosis.

The execution used one machine and one operator with filesystem-enforced Team-A
/ Team-B separation. It is therefore a machine-enforced single-operator blind
pilot, not independent-human blind testing. Strict independent blind claims
require a fresh case set and an independent operator or custodian.

Raw traces, private custody files, oracle data, host-local paths, and local
operator scripts remain outside the repository. No performance or M0 claim is
made by this report.
