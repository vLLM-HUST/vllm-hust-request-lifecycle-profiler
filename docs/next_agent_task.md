# Next Work: Integrate, Then Run Blind M0 Evaluation

## Current status

The KV-recovery implementation has completed its G1-G6 development sequence:

- G1/G2: default-off CPU wiring and NPU admission checks;
- G3: a `real-online` + `smoke-only` trace with complete recovery stages;
- G4/G5: fixed-capacity mechanism and capacity-surface captures; and
- G6: a development rank-one counterfactual for the H2D-restore mechanism.

These runs establish that the profiler can capture and analyze the intended
runtime mechanism. They are development evidence, not accepted benchmark #95
base/head performance evidence. Their causes were visible during development,
so they also cannot score the blind M0 objective. The project remains
`NOT_M0_PROVEN`.

## Immediate integration work

Take the three implementation PRs through ordinary review and CI:

- profiler PR #17;
- vLLM-HUST runtime PR #236; and
- vLLM-Ascend-HUST PR #216.

Keep tracing default-off, preserve the disabled serving path, make serving
callbacks fail open, and make incomplete formal evidence fail closed. Resolve
review findings with code, focused regression tests, the complete practical CPU
suite, and repository CI. No project-local authority, co-signature, approval,
content-freeze, digest-chain, or attestation record is required.

The CPU workflow is pinned to runtime PR #236 head
`50a6df2bef5c06e7f38107dedd9214e61ff58df1` and workload gitlink
`76e24c85bcab76ecfabb831c9444002b6efffd58`. Its fork-safe workload fixture
checks only the parent-side API. The sole full-connector test re-enters when a
complete runtime checkout and its connector test dependencies are available;
see `docs/pr17_merge_readiness.md` for the exact command.

## Research work after integration

1. Prepare fresh opaque regression cases whose causes are hidden from the
   evaluator.
2. Assign custody and reveal so the evaluator cannot see labels before it
   emits ranked candidates, confidence, unexplained residual, and any
   abstention.
3. Run the structured phase-DAG evaluator and record all outputs before reveal.
4. Run a matched flat-summary comparison arm on the same cases.
5. Reveal ground truth and score accuracy, ranking quality, abstention, and
   time-to-localize.
6. For every non-abstained rank-one prediction, run the smallest practical
   counterfactual that changes only that mechanism.
7. Update the public M0 status only if the genuine blind evaluation supports
   the claim; otherwise retain `NOT_M0_PROVEN` and report the failure modes.

## Performance-claim boundary

If a later PR claims a performance improvement, follow the canonical policy in
<https://github.com/vLLM-HUST/vllm-hust-benchmark/issues/95> and the active
registry under benchmark issue #104. That requires matched accepted base/head
`real-online` artifacts, complete resolved configuration and environment data,
raw artifacts, and at least three independent service lifecycles with every
repetition plus median and IQR.

The local G3-G6 captures must not be relabeled as benchmark-accepted evidence.
Only registry/spec hashes produced by the benchmark tooling are relevant to
that merge gate; do not create project-local approval hashes or manifests.

## Useful records

- `docs/g3_completion_record.md`
- `docs/g4_completion_record.md`
- `docs/g5_completion_record.md`
- `docs/g6_counterfactual_spec.md`
- `docs/experiment_plan.md`
- `docs/kv_recovery_runtime_callsite_map.md`
- `docs/pr17_merge_readiness.md`

Historical contract drafts under `contracts/` may explain design decisions,
but their former approval and activation-gate language is non-normative. The
current workflow is defined by `AGENTS.md`, `CONTRIBUTING.md`,
`.github/BRANCH_POLICY.md`, implementation tests, and ordinary repository CI.
