# Request Lifecycle paper artifact manifest

- Repository: `vLLM-HUST/vllm-hust-request-lifecycle-profiler`
- Source PR: `#24` (merged into `main`, then integrated into Draft PR `#22`)
- PR #24 base head: `cfecbd05cdcf7c2156f227f8560ff6c4f64e3850`
- PR #24 artifact commit: `ce8f90306de3cc5ab4b471de0faa4841f3027b05`
- Paper entry: `paper/request_lifecycle_causal_profiler/request_lifecycle_causal_profiler.tex`
- Bibliography: `paper/request_lifecycle_causal_profiler/references.bib`
- PDF: `paper/request_lifecycle_causal_profiler/request_lifecycle_causal_profiler.pdf`
- Tectonic transcript: `paper/request_lifecycle_causal_profiler/BUILD_TRANSCRIPT.txt`
- TeX log: `paper/request_lifecycle_causal_profiler/request_lifecycle_causal_profiler.log`
- Build command: `make review-pdf` (`tectonic` must be available on `PATH`)
- Build exit code: `0`
- Text build artifacts: trailing whitespace normalized after generation.
- Pages: `4`
- Visual inspection: `4/4` pages rendered with `pdftoppm`; no clipping,
  collision, unreadable table, or anomalous blank page. Page 4 intentionally
  holds the full-width evidence table followed by references.
- Layout: the transcript retains acmart font and underfull-box warnings, plus
  an overfull-vbox warning (`9.13292pt`). Visual review confirmed that it does
  not cause clipping or collision in the rendered PDF.
- Host tests: `187 passed, 9 skipped` with the documented project interpreter,
  `PYTHONPATH=src`, and materialized workload fixtures.
- `git diff --check`: exit `0`.
- NPU or experiment execution: not run.

## SHA-256 receipts

| Asset | SHA-256 |
|---|---|
| `request_lifecycle_causal_profiler.tex` | `4619cf7b56138bfad2e9fbc44fb5585d229cfb3b9abfa426770d3082d29c7575` |
| `references.bib` | `f54fb6bf7ffe8f095c49cbee9ef7dd502800d17c7ba654bb3d8280801f95b69a` |
| `request_lifecycle_causal_profiler.pdf` | `293d538f9fac6e21a83926dcd5958cc940cbdaab9469310d9b28de3284ae0988` |
| `request_lifecycle_causal_profiler.log` | `c915ba321ba9a1317f0404edabe84b5e330631daa182b99510aa53d4fa54f822` |
| `BUILD_TRANSCRIPT.txt` | `41d8ad9236a8085d4655e62034db9ab22ed12e419aebb8464bedbb50395daa67` |
| `npu6_controlled_fault_matrix.csv` | `b8d0911c34760ce44ddd26116822f6e19b9ca532decb1bcb2db37f812d5fbd99` |
| `npu6_controlled_fault_matrix.tex` | `393a59186ab2153f4968b85e1aea8464c8ba8252b5b8ffece11e6c0b47ad10e1` |

## Evidence boundary

Current evidence is limited to existing-server probes and their derived
artifacts. Streaming/decode/prefill scenario correspondence and the 12.2-second
prefill localization do not establish independent attribution accuracy or a KV,
graph, scheduler, or kernel root cause. Queue, KV-pressure, cleanup, controlled
graph-mode custody, strong matched baselines, and broad overhead remain required.
The current NPU contribution is architecture validation and instrumentation
adaptation, not a native Ascend mechanism. The recorded PR #24 artifact commits
do not incorporate or modify owner PRs `#22` or `#23`.
