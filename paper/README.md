# Paper Workspace

This template now carries a minimal, working paper scaffold rather than only a
placeholder directory.

The default manuscript workspace lives under
`paper/request_lifecycle_causal_profiler/` and includes:

- a generic LaTeX draft,
- a repo-local `tectonic` Makefile, and
- a starter bibliography file,
- `experiments/`, `results/`, `figures/`, and `tables/` subdirectories, and
- a generic paper-asset refresh script that turns result files into
	paper-facing summaries.

The scaffold also reserves two more concrete conventions that showed up in the
more mature repositories:

- `results/example_live/` for live-serving outputs that should stay distinct
	from offline or synthetic results, and
- `tables/manual/` for hand-authored table snippets that should not be
	overwritten by automated export code.

Build the scaffolded PDF from the repository root with:

```bash
make paper-assets
make paper-pdf
```

Or invoke the paper workspace directly with:

```bash
make -C paper/request_lifecycle_causal_profiler paper-assets
make -C paper/request_lifecycle_causal_profiler pdf
```

When an existing repository needs only the minimal placeholder manuscript
without copying this whole template tree, use
`scripts/render_placeholder_paper_scaffold.py` from the template root. That
script renders the same placeholder Makefile and `.tex` draft into the target
repository while keeping the placeholder paper text owned here.

Derived repositories should rename this subdirectory to the actual paper topic
and then replace the placeholder manuscript with repo-specific content,
figures, and measured evidence. The directory convention itself should usually
remain stable so derived repos keep a predictable `paper-assets -> pdf` build
contract.