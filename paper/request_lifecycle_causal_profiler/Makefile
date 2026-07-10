TECTONIC ?= tectonic
PYTHON ?= python3
PAPER_TEX := request_lifecycle_causal_profiler.tex
PAPER_PDF := request_lifecycle_causal_profiler.pdf
OUTDIR := build
CACHE_DIR := .tectonic-cache
CONFIG_DIR := .tectonic-config
REPO_ROOT := $(abspath $(CURDIR)/../..)
LLM_OPTIMIZATIONS_ROOT ?= $(abspath $(REPO_ROOT)/../llm-optimizations)
LLM_OPTIMIZATIONS_PDF_DIR ?= $(LLM_OPTIMIZATIONS_ROOT)/docs/papers
LLM_OPTIMIZATIONS_PDF_NAME ?= general-plugin-template__request_lifecycle_causal_profiler.pdf
EXPERIMENTS_DIR := experiments
RESULTS_DIR := results
LIVE_RESULTS_DIR := $(RESULTS_DIR)/example_live
PAPER_ASSET_OUTPUT_DIR := $(RESULTS_DIR)/paper_assets_latest
FIGURES_DIR := figures
GENERATED_FIGURES_DIR := $(FIGURES_DIR)/generated
TABLES_DIR := tables
MANUAL_TABLES_DIR := $(TABLES_DIR)/manual
GENERATED_TABLES_DIR := $(TABLES_DIR)/generated
PAPER_ASSET_EXPORT_SCRIPT := $(EXPERIMENTS_DIR)/export_paper_assets.py
PAPER_ASSET_MANIFEST := $(PAPER_ASSET_OUTPUT_DIR)/paper_asset_manifest.json
PAPER_ASSET_SUMMARY_MD := $(PAPER_ASSET_OUTPUT_DIR)/paper_asset_summary.md
PAPER_ASSET_SUMMARY_TEX := $(GENERATED_TABLES_DIR)/results_summary.tex

.DEFAULT_GOAL := help

.PHONY: help paper-assets pdf clean

help:
	@printf '%s\n' \
		'Paper targets:' \
		'  make paper-assets  Refresh generated paper-facing assets from results/' \
		'  make pdf    Build the standalone plugin artifact draft with tectonic' \
		'  make clean  Remove local LaTeX build outputs'

paper-assets: $(PAPER_ASSET_EXPORT_SCRIPT)
	mkdir -p $(RESULTS_DIR) $(LIVE_RESULTS_DIR) $(FIGURES_DIR) $(TABLES_DIR) $(MANUAL_TABLES_DIR) $(PAPER_ASSET_OUTPUT_DIR)
	$(PYTHON) $(PAPER_ASSET_EXPORT_SCRIPT) \
		--results-dir $(RESULTS_DIR) \
		--live-results-dir $(LIVE_RESULTS_DIR) \
		--output-dir $(PAPER_ASSET_OUTPUT_DIR) \
		--figure-dir $(GENERATED_FIGURES_DIR) \
		--table-dir $(GENERATED_TABLES_DIR) \
		--manifest-json $(PAPER_ASSET_MANIFEST) \
		--summary-markdown $(PAPER_ASSET_SUMMARY_MD) \
		--summary-tex $(PAPER_ASSET_SUMMARY_TEX)

pdf: paper-assets
	mkdir -p $(OUTDIR) $(CACHE_DIR) $(CONFIG_DIR)
	XDG_CACHE_HOME=$(CURDIR)/$(CACHE_DIR) XDG_CONFIG_HOME=$(CURDIR)/$(CONFIG_DIR) $(TECTONIC) --keep-logs --keep-intermediates --outdir $(OUTDIR) $(PAPER_TEX)
	@if [ -d "$(LLM_OPTIMIZATIONS_ROOT)" ] && [ -f "$(OUTDIR)/$(PAPER_PDF)" ]; then \
		python3 "$(LLM_OPTIMIZATIONS_ROOT)/scripts/export_paper_pdf.py" \
			--workspace-file "$(LLM_OPTIMIZATIONS_ROOT)/llm-optimizations.code-workspace" \
			--repo-root "$(REPO_ROOT)" \
			--source-pdf "$(OUTDIR)/$(PAPER_PDF)" \
			--output-name "$(LLM_OPTIMIZATIONS_PDF_NAME)" \
			--destination-dir "$(LLM_OPTIMIZATIONS_PDF_DIR)"; \
	fi

clean:
	rm -rf $(OUTDIR) $(GENERATED_FIGURES_DIR) $(GENERATED_TABLES_DIR)
	rm -rf $(PAPER_ASSET_OUTPUT_DIR)
	rm -f *.aux *.log *.out *.toc *.blg *.bbl $(PAPER_PDF)
	rm -rf $(CACHE_DIR) $(CONFIG_DIR)