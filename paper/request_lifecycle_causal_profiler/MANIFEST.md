# Request Lifecycle paper artifact manifest

- Repository: `intellistream/vllm-request-lifecycle-profiler-plugin`
- Draft PR: `#24`
- Base head: `cfecbd05cdcf7c2156f227f8560ff6c4f64e3850`
- Artifact commit: `ce8f90306de3cc5ab4b471de0faa4841f3027b05`
- Paper entry: `paper/request_lifecycle_causal_profiler/request_lifecycle_causal_profiler.tex`
- Bibliography: `paper/request_lifecycle_causal_profiler/references.bib`
- PDF: `paper/request_lifecycle_causal_profiler/request_lifecycle_causal_profiler.pdf`
- Tectonic transcript: `paper/request_lifecycle_causal_profiler/BUILD_TRANSCRIPT.txt`
- TeX log: `paper/request_lifecycle_causal_profiler/request_lifecycle_causal_profiler.log`
- Build command: `PATH=/home/shuhao/.conda/envs/neuromem/bin:$PATH make review-pdf`
- Build exit code: `0`
- Pages: `4`
- Visual inspection: `4/4` pages rendered with `pdftoppm`; no clipping,
  collision, unreadable table, or anomalous blank page. Page 4 intentionally
  holds the full-width evidence table followed by references.
- Layout: no overfull box; transcript retains acmart font and underfull-box
  warnings.
- Host tests: `123 passed, 9 skipped, 4 failed`; all four failures require the
  unmaterialized `third_party/llm-serving-workloads` package in the clean
  worktree. No environment or student code was changed to mask them.
- `git diff --check`: exit `0`.
- NPU or experiment execution: not run.

## SHA-256 receipts

| Asset | SHA-256 |
|---|---|
| `request_lifecycle_causal_profiler.tex` | `e109ef59f04170bee61d01359da729a82d0fe7eaa837c4ebbbf7b0c74fe1f54c` |
| `references.bib` | `f54fb6bf7ffe8f095c49cbee9ef7dd502800d17c7ba654bb3d8280801f95b69a` |
| `request_lifecycle_causal_profiler.pdf` | `18827050c14fe8b55e8fa301f3142b278a469f247352cadff4daf0a7a1884574` |
| `request_lifecycle_causal_profiler.log` | `5a27a9b405d89c33d64dfe4faa04b4c1f4cf9cda8fcc80b585f3453bed889e32` |
| `BUILD_TRANSCRIPT.txt` | `477dd8436444e898f4ce5bf74d030d11897e3d5c4b65ae69c4baeca167c1d461` |
| `npu6_controlled_fault_matrix.csv` | `b8d0911c34760ce44ddd26116822f6e19b9ca532decb1bcb2db37f812d5fbd99` |
| `npu6_controlled_fault_matrix.tex` | `393a59186ab2153f4968b85e1aea8464c8ba8252b5b8ffece11e6c0b47ad10e1` |

## Evidence boundary

Current evidence is limited to existing-server probes and their derived
artifacts. Streaming/decode/prefill scenario correspondence and the 12.2-second
prefill localization do not establish independent attribution accuracy or a KV,
graph, scheduler, or kernel root cause. Queue, KV-pressure, cleanup, controlled
graph-mode custody, strong matched baselines, and broad overhead remain required.
The current NPU contribution is architecture validation and instrumentation
adaptation, not a native Ascend mechanism. This branch does not incorporate or
modify owner PRs `#22` or `#23`.
