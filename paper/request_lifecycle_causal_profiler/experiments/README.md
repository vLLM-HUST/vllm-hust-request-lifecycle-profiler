# Paper Experiments Helpers

Keep paper-only export, plotting, and table-refresh helpers here.

In the template, `export_paper_assets.py` is intentionally generic: it scans
the paper `results/` directory, emits a file manifest, stages any figure-like
files into `figures/generated/`, and generates a LaTeX summary snippet under
`tables/generated/`.

The maintained exporter additionally consumes verified `BENCHMARK_HISTORY_ROOT`
and `BENCHMARK_COLLECTION_ROOT` inputs (see [EVIDENCE.md](../../../EVIDENCE.md)).
Both must be outside the checkout. Missing raw captures must not be synthesized
from compact summaries. Local generated tables/figures/CSVs are derived build
outputs, not independent measurements; publish experiment derivatives in benchmark.

Root `make top-tier-readiness` reads local summaries produced by its prerequisite
analysis targets. Those output consumers must not be redirected to historical
summaries: doing so would silently validate old outputs instead of the current
derivation. This no-NPU command is not an online qualification or a blind study.
