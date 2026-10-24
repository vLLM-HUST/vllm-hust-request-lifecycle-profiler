# M0 Evaluation Pipeline (development-level, 2026-08-11)

[Complete historical original](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/5a4439b91923c5a1c5cf9a1a1dac729a3f32846c/archive/mod-targeted-20261023/profiler-m0-consumers/snapshot/docs/m0_evaluation_pipeline.md).
[Evidence and consumer map](m0_consumer_evidence.md). `NOT_M0_PROVEN`; no new
experiment, historical-input recovery or current device readiness is implied.

> Implements issue #1's first-stage evaluation machinery: normalize request
> traces into a phase DAG, diff baseline vs anomaly on the critical path, rank
> top-k mechanism candidates with confidence and unexplained residual, and
> score against ground truth. This is the **development-level** evaluator; the
> Team-A custody/reveal blind protocol is a separate team-frozen activity.

## Pipeline stages

1. **Normalize** — per-request phase vectors:
   - General phases: `tokenization, queueing, prefill, decode, streaming,
     cleanup` (from `runtime_internal_spans.csv` / runtime-hook traces).
   - KV-recovery phases: `kv_recovery` = `preempt -> first_prefill_or_decode`
     span (from `trace.rlp-kv-recovery.*.jsonl`) plus client end-to-end timing.
2. **Aggregate** — per-phase median over requests (robust).
3. **Critical-path diff** — per-phase delta `anomaly_median - baseline_median`.
4. **Rank** — mechanisms by positive delta share, sorted descending; top-1/top-3
   share = fraction of total positive delta explained.
5. **Residual** — total positive delta minus top-1 delta (unexplained).
6. **Abstain rule** — abstain (`no_single_root_cause` / `insufficient_evidence`)
   if total delta is below a floor or the top-1 share is below a dominance
   threshold.
7. **Score** (when ground truth is known) — top-1/top-3 match, MRR.

## Historical development validation (NOT blind-scored)

The complete original above retains the four-case numerical table and dated
test count. The old validation JSON and private G4/G6 input runs have not been
matched in the pinned public capsules; the table is not a recovered raw file.
The concurrency CSV is available through the exact [member map](m0_consumer_evidence.json).

Module: `src/vllm_request_lifecycle_profiler/m0_evaluation.py`.
Driver: `.benchmarks/run_m0_development_validation.py`.
Unit tests: `tests/test_m0_evaluation.py` (current CI, not a dated count).

The driver now requires explicit `--g4-runs-root`, `--collection-root` and
`--output-dir`. Inputs must be external and present; output must be a new
absolute external directory disjoint from inputs. Missing or ambiguous run
prefixes and missing measured concurrency arms fail before writing a result.
There is no fallback to old machine paths or the dated result directory.

Case A retains a historical max-total heuristic linking a recovery span to a
client row, not an exact request-identity join. Operator-provided private inputs
are not authenticated by this driver. New outputs are labeled derived-artifact,
NOT_M0_PROVEN and not blind-scored; they cannot replace the archived observations.
No replay with the unavailable private inputs was performed in this migration.

## Boundary

- Development-level only: ground truth is known and not hidden. The archived record describes
  localization of known anomalies and abstention, not a fresh validation result.
- It does **not** establish blind accuracy/MRR/time-to-localize; that requires
  the separately frozen Team-A custody/reveal protocol with fresh opaque cases.
- `time-to-localize` is currently represented by ground-truth rank (rank 1 ⇒
  fastest localization); wall-clock human localization time is out of scope.
- Project remains `NOT_M0_PROVEN`.
