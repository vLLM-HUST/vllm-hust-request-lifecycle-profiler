# Canonical historical data

This migration batch is stored only in [vllm-hust-benchmark](https://github.com/vLLM-HUST/vllm-hust-benchmark/tree/2144d58de108cddaff3800fdcbf12dc9d3ab1d18/archive/mod-consumers-20261023/profiler).
`BENCHMARK_EVIDENCE.json` pins the manifest and its SHA256. The manifest preserves original
repository/commit/path identities, failures and every file hash. This is custody, not a new result.

```bash
python scripts/fetch_mod_consumer_evidence.py --destination /absolute/new/external/evidence
export BENCHMARK_EVIDENCE_ROOT=/absolute/new/external/evidence
```

The destination must be new and outside this checkout. The downloader verifies the archive and
every member before writing, rejects links/unsafe paths, and never falls back to local copies.
Use `$BENCHMARK_EVIDENCE_ROOT/.benchmarks/results/m0_issue19_public/20260822-sanitized-corrected-paired-10/` for this batch's original data.
Existing generation commands may still write new local outputs; do not commit them here.

Other historical directories are not declared migrated by this batch. Original failures and
diagnostic/NO_GO scopes remain unchanged. No hardware experiment is required to read this archive.

After downloading and exporting the root, run `make issue19-public-evidence-verify` or the
ordinary CPU tests. The semantic test still requires the exact original NO_GO decision and
272 verified public files; the capsule additionally preserves the original context/manifest.


## Additional historical directories

[Canonical history manifest](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/afd47a8e9964b71844dec75a8e908f279ae98202/archive/mod-history-20261023/profiler/manifest.json) lists original paths, sizes and SHA256.
This is a separate capsule from BENCHMARK_EVIDENCE.json; do not reuse its destination.
No hardware experiment or new performance acceptance is implied.

```sh
python scripts/fetch_mod_consumer_evidence.py --config BENCHMARK_HISTORY.json \
  --destination /absolute/new/external/history
```

The restored root preserves these original paths:

- `.benchmarks/results/npu6_existing_server_probe_blocked/`
- `.benchmarks/results/npu6_existing_server_trace_overhead_smoke/`
- `docs/claim_ledger.md`

Frozen reports retain original labels and local paths; these do not assert that omitted captures were recovered.

Set `BENCHMARK_HISTORY_ROOT` to this root for CPU tests and paper `make paper-assets`. The exporter requires `--historical-evidence-root`; missing overhead input fails closed.


## Remaining collections (formal / handoff / TP4-TP8 / profiler)

[Member manifest](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/812ef01ae992475d4ce6a3bb6a6ce4bda43b5f12/archive/mod-collections-20261023/profiler/manifest.json) preserves the source commit and every original hash.

```sh
python scripts/fetch_mod_consumer_evidence.py --config BENCHMARK_COLLECTION.json \
  --destination /absolute/new/external/collection
export BENCHMARK_COLLECTION_ROOT=/absolute/new/external/collection
```

This root is separate from BENCHMARK_EVIDENCE_ROOT and BENCHMARK_HISTORY_ROOT.
Do not execute archived scripts; use the maintained repository validators.
All paths below are archive-relative; generation commands may still produce ignored local outputs.

- `.benchmarks/results/`

No tracked originals or forwarding stubs remain under `.benchmarks/results/`.
This entrypoint replaces the old local navigation; tests/test_collection_evidence_boundary.py
checks the empty tracked-results boundary. Maintained consumers stay outside that directory.

Paper export additionally requires --collection-evidence-root; offline Make targets use BENCHMARK_COLLECTION_ROOT. Missing full runtime JSONL inputs stay missing: compact summaries are not substitutes. Generated paper presentation outputs remain a separate projection, not new measurements.

The old M0 development validator now reads its concurrency CSV from this external root.
Its separate `/root/kv-recovery-service-g4/runs` inputs are not supplied by this capsule;
the old G1/G2 preflight scripts likewise require their separately generated inputs.
These historical local workflows were not executed or declared reproducible by this migration.
