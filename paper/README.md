# Paper workspace

Current status: research draft, NOT_M0_PROVEN. The fixed Issue19 scenario is
NO_GO, not a reconciliation speedup or rejection of the research topic.

The [complete original paper archive](https://github.com/vLLM-HUST/vllm-hust-benchmark/releases/download/evidence-profiler-research-20261024-v1/profiler-research-20261024.tar.gz) preserves the historical PDF,
manuscript, build transcript/log, CSVs, generated TeX tables, figure and original
manifest under `snapshot/paper/`. Read the PDF from the verified external
`BENCHMARK_RESEARCH_ROOT`; see [EVIDENCE.md](../EVIDENCE.md).

The maintained repository retains exporter/build code, bibliography, template
fixtures and methodological documentation. Experimental outputs belong in
benchmark. `make paper-assets` is a fresh local derivation using the existing
external history/collection roots; it does not rewrite the frozen manuscript.

For a historical paper rebuild, set `BENCHMARK_RESEARCH_ROOT` and a new absolute
`PAPER_REVIEW_OUTPUT` outside this checkout, then run `make paper-pdf` (Tectonic
required). The maintained staging tool verifies source hashes before copying
only manuscript/bibliography/table/figure inputs. It never executes archived
Makefiles or Python helpers. The new PDF/log are rebuild outputs, not new
measurements, and need not match the historical PDF byte-for-byte.

Missing full traces, private raw records, G1/G4 captures and blind/causal
evaluation gaps remain missing. Migration does not authorize hardware runs.
