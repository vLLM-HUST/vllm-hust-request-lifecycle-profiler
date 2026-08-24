# Issue 19 OASST1 workload

Issue #19 uses human-authored OpenAssistant conversations as fixed request
content. The source is the `third_party/oasst1` submodule at revision
`fdf72ae0827c1cda404aff25b6603abec9e3399b`; the selected file is
`2023-04-12_oasst_ready.trees.jsonl.gz` under the dataset's Apache-2.0
license. This is real conversation content, not a production arrival trace.

## Materialization

The Git checkout contains a Git LFS pointer. Materialize the object into the
ignored local cache with:

```bash
PYTHONPATH=src python -m vllm_request_lifecycle_profiler.oasst1_workload
```

The command first requires the exact submodule revision. It then validates the
download against the size and object ID recorded by the dataset's own Git LFS
pointer and checks the complete gzip stream. No raw OASST1 data is added to the
profiler Git history.

## Deterministic projection

`build_oasst1_repetitions()` applies the pre-registered projection:

1. Keep English, non-synthetic, non-deleted, reviewed paths whose `pii` and
   `not_appropriate` labels are zero or absent.
2. Map `prompter` to `user`, preserve prior `assistant` turns, and end each
   request at a `user` turn.
3. Keep the longest eligible path per tree. Equal-length paths use the smallest
   source message ID as a deterministic tie-breaker.
4. Sort by descending character count, tree ID, and source message ID, then
   select the first 640 distinct trees.
5. Repetition `r` receives pool indices whose index modulo 10 equals `r`, then
   orders its 64 requests by tree ID and source message ID.

The projection manifest contains only request/source IDs, order, character
count, and generation settings. It excludes user IDs, moderation labels, raw
prompt text, and unused assistant targets. Baseline and any later treatment
must consume the same manifest. The production adapter verifies the source
against the pinned submodule pointer again before parsing; `verify_source=false`
exists only for small repository test fixtures.

Before a real run, apply the pinned Qwen2.5-14B-Instruct tokenizer with
`preflight_context_lengths()`. The Issue #19 specialty target uses
`max_model_len=10880`, the exact block-aligned capacity exposed by its fixed
2-GiB KV cache for this model. A request exceeding `10880 - 192` input tokens
fails the preflight; the adapter never truncates or resamples it. This corrected
specialty limit is separate from any 32K official-target experiment.

This module only prepares request content. It does not enable lifecycle
reconciliation, inject failures, start a service, or constitute M0/performance
evidence.
