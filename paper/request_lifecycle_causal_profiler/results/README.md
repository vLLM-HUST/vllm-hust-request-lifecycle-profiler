# Results

Keep raw or intermediate experiment outputs consumed by the paper build here.

The template's generic `make paper-assets` path scans this directory,
generates a manifest and Markdown summary, stages any figure-like files into
`figures/generated/`, and emits a LaTeX summary snippet under
`tables/generated/`.

Derived repositories should replace these placeholder contents with the real
outputs their paper wants to summarize.