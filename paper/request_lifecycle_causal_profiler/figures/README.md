# Figures

Keep stable figure paths for the paper here.

The generic `make paper-assets` flow stages any figure-like files already found
under `results/` into `figures/generated/` so the manuscript can refer to a
predictable paper-local figure directory.

Derived repositories can keep hand-authored figures here as well, but should
avoid forcing LaTeX to reference deep benchmark-output paths directly.