# Paper Experiments Helpers

Keep paper-only export, plotting, and table-refresh helpers here.

In the template, `export_paper_assets.py` is intentionally generic: it scans
the paper `results/` directory, emits a file manifest, stages any figure-like
files into `figures/generated/`, and generates a LaTeX summary snippet under
`tables/generated/`.

Derived repositories should replace or extend this helper with their real
paper-facing export logic while keeping the external `make paper-assets` entry
stable.