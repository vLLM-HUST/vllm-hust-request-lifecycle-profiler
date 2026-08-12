# PR #17 Merge-Readiness Checklist

This checklist records the ordinary integration boundary for profiler PR #17.
It does not create an approval, authority, attestation, or content-freeze
process.

## Normative policy

The repository has one current contribution and integration policy:

- [`CONTRIBUTING.md`](../CONTRIBUTING.md): environment, workload, evidence
  labels, claims, tests, and branch naming;
- [`.github/BRANCH_POLICY.md`](../.github/BRANCH_POLICY.md): branch and merge
  lifecycle;
- [`AGENTS.md`](../AGENTS.md): current project boundaries and evidence rules;
- [benchmark issue #95](https://github.com/vLLM-HUST/vllm-hust-benchmark/issues/95):
  canonical requirements only when making a formal performance claim.

Historical contract drafts may remain for technical context, but their former
authority, approval, attestation, digest-chain, and joint-admission language is
non-normative.

## Retired files removed by PR #17

PR #17 intentionally removes the following 24 project-process records:

- `contracts/p0/owner-freeze-approval.json`
- `contracts/p0/p0-manifest.json`
- `contracts/p1/benchmark-134-fixed-8gib-config-candidate.json`
- `contracts/p1/benchmark-134-fixed-8gib-config-candidate.r2.json`
- `contracts/p1/g0-mapping-remediation-cpu-result.json`
- `contracts/p1/g0-pinned-pair-cpu-result.json`
- `contracts/p1/g1-cpu-wiring-owner-authorization.json`
- `contracts/p1/g1-cpu-wiring-owner-reauthorization.r2.json`
- `contracts/p1/g1-cpu-wiring-reauthorization-candidate.r2.json`
- `contracts/p1/g1-default-off-cpu-implementation-attestation.r0.json`
- `contracts/p1/g1-default-off-cpu-implementation-attestation.r1.json`
- `contracts/p1/g1-default-off-cpu-implementation-attestation.r2.json`
- `contracts/p1/g1-default-off-cpu-implementation-attestation.r3.json`
- `contracts/p1/issue2-kv-recovery-mapping-approval-candidate.json`
- `contracts/p1/issue2-kv-recovery-mapping-authority-approval.json`
- `contracts/p1/kv-offload-base-mode-overlay-approval-candidate.json`
- `contracts/p1/kv-offload-base-mode-overlay-owner-approval.json`
- `contracts/p1/kv-offload-base-mode-overlay-owner-ratification-candidate.r2.json`
- `contracts/p1/kv-offload-base-mode-overlay-owner-ratification.r2.json`
- `contracts/p1/kv-recovery-observer-policy-approval-candidate.json`
- `contracts/p1/kv-recovery-observer-policy-profile-p0-owner-approval.json`
- `contracts/p1/kv-recovery-observer-policy.v0-draft.json`
- `contracts/p1/kv-recovery-profile-approval-candidate.json`
- `contracts/p1/kv-recovery-profile-owner-approval.json`

It also removes the following 11 tests whose purpose was to enforce those
records rather than product behavior:

- `tests/test_current_owner_records.py`
- `tests/test_g0_contract_candidate_integrity.py`
- `tests/test_g0_mapping_remediation_result.py`
- `tests/test_g0_pinned_pair_probe.py`
- `tests/test_g1_default_off_cpu_attestation.py`
- `tests/test_g1_default_off_cpu_attestation_r1.py`
- `tests/test_g1_default_off_cpu_attestation_r2.py`
- `tests/test_g1_default_off_cpu_attestation_r3.py`
- `tests/test_issue2_mapping_authority_approval.py`
- `tests/test_issue2_mapping_remediation.py`
- `tests/test_owner_authorization_integrity.py`

## Claim boundary

- G3 is a `real-online` + `smoke-only` development capture.
- G4 and G5 are development mechanism/capacity captures.
- G6 is a development counterfactual.
- None is benchmark #95 accepted performance evidence.
- `README.md`, `docs/experiment_plan.md`, the call-site map, and generated M0
  evaluation reports retain `NOT_M0_PROVEN`.

## CPU test boundary

The ordinary CPU workflow uses:

- runtime PR #236 head
  `50a6df2bef5c06e7f38107dedd9214e61ff58df1`;
- workload gitlink `76e24c85bcab76ecfabb831c9444002b6efffd58`;
- Python 3.10 and 3.11;
- complete profiler pytest, critical Ruff checks, and sdist/wheel builds.

The sole bounded skip is
`test_actual_runtime_connector_flow_captures_full_h2d_recovery`. It imports the
complete vLLM package, `OffloadingConnector`, and vLLM's connector test helpers,
which are intentionally absent from the fork-safe ABI-only CI checkout.

The test re-enters when a trusted environment provides a complete vLLM-HUST
checkout at the runtime PR #236 head with its connector test dependencies.
Set `VLLM_HUST_FULL_SRC` to that checkout and run:

```bash
PYTHONPATH=src:$VLLM_HUST_FULL_SRC \
VLLM_HUST_G1_SRC=$VLLM_HUST_FULL_SRC \
pytest -q \
  tests/test_kv_recovery_runtime_integration.py::test_actual_runtime_connector_flow_captures_full_h2d_recovery
```

The fork-safe workload fixture remains an API compatibility test only. A
trusted evidence run must use the real workload checkout at the recorded
gitlink.

## Independently implemented engineering fixes

PR #17 contains none of PR #18's authority-restoration changes. It independently
implements and tests only the useful engineering changes:

- no synchronous logging handler on the producer failure path;
- H2D edge `trace_id` validation;
- canonical base/profile shard content-integrity verification;
- the `regex` test dependency;
- the fork-safe workload ABI fixture; and
- ordinary Python 3.10/3.11 CPU CI and package builds.

The final PR comment records the fresh-checkout command/result map and exact
Git head after all current remote checks complete.
