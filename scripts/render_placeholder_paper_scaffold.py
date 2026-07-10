#!/usr/bin/env python3

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PlaceholderPaperSpec:
    repo_root: Path
    paper_subdir: str
    paper_slug: str
    export_prefix: str
    title: str
    problem_frame: str
    artifact_boundary: str


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create a repo-local placeholder paper scaffold for a single optimization repository."
        )
    )
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--paper-subdir", required=True)
    parser.add_argument("--paper-slug", required=True)
    parser.add_argument("--export-prefix")
    parser.add_argument("--title", required=True)
    parser.add_argument("--problem-frame", required=True)
    parser.add_argument("--artifact-boundary", required=True)
    return parser


def render_makefile(spec: PlaceholderPaperSpec) -> str:
    return f"""TECTONIC ?= tectonic
PAPER_TEX := {spec.paper_slug}.tex
PAPER_PDF := {spec.paper_slug}.pdf
CACHE_DIR := .tectonic-cache
CONFIG_DIR := .tectonic-config
REPO_ROOT := $(abspath $(CURDIR)/../..)
LLM_OPTIMIZATIONS_ROOT ?= $(abspath $(REPO_ROOT)/../llm-optimizations)
LLM_OPTIMIZATIONS_PDF_DIR ?= $(LLM_OPTIMIZATIONS_ROOT)/docs/papers
LLM_OPTIMIZATIONS_PDF_NAME ?= {spec.export_prefix}__{spec.paper_slug}.pdf

.DEFAULT_GOAL := help

.PHONY: help pdf clean

help:
	@printf '%s\\n' \\
		'Paper targets:' \\
		'  make pdf    Build the placeholder paper scaffold with tectonic' \\
		'  make clean  Remove local LaTeX build outputs'

pdf:
	mkdir -p $(CACHE_DIR) $(CONFIG_DIR)
	XDG_CACHE_HOME=$(CURDIR)/$(CACHE_DIR) XDG_CONFIG_HOME=$(CURDIR)/$(CONFIG_DIR) $(TECTONIC) --keep-logs --keep-intermediates $(PAPER_TEX)
	@if [ -d "$(LLM_OPTIMIZATIONS_ROOT)" ] && [ -f "$(PAPER_PDF)" ]; then \\
		python3 "$(LLM_OPTIMIZATIONS_ROOT)/scripts/export_paper_pdf.py" \\
			--workspace-file "$(LLM_OPTIMIZATIONS_ROOT)/llm-optimizations.code-workspace" \\
			--repo-root "$(REPO_ROOT)" \\
			--source-pdf "$(PAPER_PDF)" \\
			--output-name "$(LLM_OPTIMIZATIONS_PDF_NAME)" \\
			--destination-dir "$(LLM_OPTIMIZATIONS_PDF_DIR)"; \\
	fi

clean:
	rm -f *.aux *.log *.out *.toc *.blg *.bbl $(PAPER_PDF)
	rm -rf $(CACHE_DIR) $(CONFIG_DIR)
"""


def render_tex(spec: PlaceholderPaperSpec) -> str:
    return f"""\\documentclass[conference]{{IEEEtran}}

\\usepackage[T1]{{fontenc}}
\\usepackage{{amsmath,amssymb,amsfonts}}
\\usepackage{{booktabs}}
\\usepackage{{graphicx}}
\\usepackage{{xcolor}}

\\begin{{document}}

\\title{{{spec.title}}}

\\author{{\\IEEEauthorblockN{{Anonymous Authors}}}}

\\maketitle

\\begin{{abstract}}
This draft is a placeholder paper scaffold for the \\texttt{{{spec.repo_root.name}}} optimization line. The current repository focuses on {spec.problem_frame}. At this stage, the contribution is bounded to a compilable paper path, an explicit artifact boundary, and a truthful statement of what still needs to be measured before any systems claim is justified. {spec.artifact_boundary} The draft therefore exists to reserve the paper slot and keep the repository aligned with the workspace template requirement that each optimization line can export at least a placeholder article into the centralized paper bundle.
\\end{{abstract}}

\\begin{{IEEEkeywords}}
LLM inference, systems paper scaffold, placeholder artifact
\\end{{IEEEkeywords}}

\\section{{Problem Frame}}

The intended optimization seam in this repository is {spec.problem_frame}. That is a systems problem, but this repository is not yet presenting a claim-bearing mechanism evaluation. The placeholder article exists so that future work can replace bounded placeholder text with measured design, implementation, and evaluation content without first rebuilding the paper workflow from scratch.

\\section{{Artifact Boundary}}

This paper currently makes only three bounded claims.

\\begin{{itemize}}
\\item The repository owns a concrete optimization topic and paper slot.
\\item The repository can compile a local placeholder manuscript with a repo-local \\texttt{{tectonic}} workflow.
\\item The repository can export that manuscript into the centralized \\texttt{{llm-optimizations/docs/papers/}} bundle using workspace-order numbering.
\\end{{itemize}}

The draft does not claim realized runtime reuse, scheduler benefit, memory savings, latency improvement, or end-to-end serving gains.

\\section{{Placeholder Evaluation Contract}}

Before this repository should make a systems claim, the placeholder article should be replaced with at least the following concrete evidence layers.

\\begin{{enumerate}}
\\item mechanism-specific implementation details at the owning runtime seam,
\\item narrow validation or workload-grounded probes that show the intended control surface is real, and
\\item end-to-end serving measurements that justify any broad performance claim.
\\end{{enumerate}}

Until those layers exist, this placeholder draft should be read as an artifact scaffold and paper reservation, not as an optimization result.

\\section{{Next Replacement Steps}}

The next revision should replace this placeholder text with a repository-specific problem statement, runtime design, experiment matrix, and measured evidence. If those materials do not exist yet, the repository should keep the language bounded and use this draft only to preserve a valid paper-export path.

\\section{{Conclusion}}

The workspace template requires every optimization line to export at least a placeholder article. This repository now satisfies that boundary with a compilable draft that names the problem area, states the artifact boundary, and leaves room for future measured systems work.

\\end{{document}}
"""


def scaffold_placeholder_paper(spec: PlaceholderPaperSpec) -> list[Path]:
    paper_root = spec.repo_root / spec.paper_subdir
    paper_root.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []

    files = {
        paper_root / "Makefile": render_makefile(spec),
        paper_root / f"{spec.paper_slug}.tex": render_tex(spec),
    }
    for path, content in files.items():
        if path.exists():
            continue
        path.write_text(content, encoding="utf-8")
        created.append(path)
    return created


def main() -> int:
    args = build_parser().parse_args()
    repo_root = Path(args.repo_root).expanduser().resolve()
    spec = PlaceholderPaperSpec(
        repo_root=repo_root,
        paper_subdir=args.paper_subdir,
        paper_slug=args.paper_slug,
        export_prefix=args.export_prefix or repo_root.name,
        title=args.title,
        problem_frame=args.problem_frame,
        artifact_boundary=args.artifact_boundary,
    )
    for path in scaffold_placeholder_paper(spec):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())