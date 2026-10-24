TECTONIC ?= tectonic
SCRIPT ?= script
PYTHON ?= python3
SOURCE_DATE_EPOCH ?= 0
PAPER_TEX := request_lifecycle_causal_profiler.tex
PAPER_PDF := request_lifecycle_causal_profiler.pdf
OUTDIR := build
CACHE_DIR := .tectonic-cache
CONFIG_DIR := .tectonic-config
REPO_ROOT := $(abspath $(CURDIR)/../..)
PAPER_REVIEW_OUTPUT ?=
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
PDF_CANONICALIZE_SCRIPT := $(EXPERIMENTS_DIR)/canonicalize_pdf.py
PAPER_ASSET_MANIFEST := $(PAPER_ASSET_OUTPUT_DIR)/paper_asset_manifest.json
PAPER_ASSET_SUMMARY_MD := $(PAPER_ASSET_OUTPUT_DIR)/paper_asset_summary.md
PAPER_ASSET_SUMMARY_TEX := $(GENERATED_TABLES_DIR)/results_summary.tex

.DEFAULT_GOAL := help

.PHONY: help paper-assets pdf review-pdf clean

help:
	@printf '%s\n' \
		'Paper targets:' \
		'  make paper-assets  Refresh generated paper-facing assets from results/' \
		'  make pdf    Build the standalone plugin artifact draft with tectonic' \
		'  make review-pdf  Rebuild verified benchmark paper inputs in a new external directory' \
		'  make clean  Remove local LaTeX build outputs'

paper-assets: $(PAPER_ASSET_EXPORT_SCRIPT)
	@test -n "$(BENCHMARK_COLLECTION_ROOT)" || (echo 'Set BENCHMARK_COLLECTION_ROOT to the verified external collection'; exit 1)
	@test -n "$(BENCHMARK_HISTORY_ROOT)" || (echo 'Set BENCHMARK_HISTORY_ROOT to the verified external capsule (see ../../EVIDENCE.md)'; exit 1)
	mkdir -p $(RESULTS_DIR) $(LIVE_RESULTS_DIR) $(FIGURES_DIR) $(TABLES_DIR) $(MANUAL_TABLES_DIR) $(PAPER_ASSET_OUTPUT_DIR)
	$(PYTHON) $(PAPER_ASSET_EXPORT_SCRIPT) \
		--results-dir $(RESULTS_DIR) \
		--historical-evidence-root "$(BENCHMARK_HISTORY_ROOT)" \
		--collection-evidence-root "$(BENCHMARK_COLLECTION_ROOT)" \
		--live-results-dir $(LIVE_RESULTS_DIR) \
		--output-dir $(PAPER_ASSET_OUTPUT_DIR) \
		--figure-dir $(GENERATED_FIGURES_DIR) \
		--table-dir $(GENERATED_TABLES_DIR) \
		--manifest-json $(PAPER_ASSET_MANIFEST) \
		--summary-markdown $(PAPER_ASSET_SUMMARY_MD) \
		--summary-tex $(PAPER_ASSET_SUMMARY_TEX)

pdf: review-pdf

review-pdf:
	@test -n "$(BENCHMARK_RESEARCH_ROOT)" -a -n "$(PAPER_REVIEW_OUTPUT)" || (echo 'Set verified BENCHMARK_RESEARCH_ROOT and a new external PAPER_REVIEW_OUTPUT'; exit 1)
	$(PYTHON) $(REPO_ROOT)/scripts/stage_paper_review.py \
		--evidence-root "$(BENCHMARK_RESEARCH_ROOT)" \
		--output-dir "$(PAPER_REVIEW_OUTPUT)" --compile

clean:
	rm -rf $(OUTDIR) $(GENERATED_FIGURES_DIR) $(GENERATED_TABLES_DIR)
	rm -rf $(PAPER_ASSET_OUTPUT_DIR)
	rm -f *.aux *.log *.out *.toc *.blg *.bbl $(PAPER_PDF)
	rm -rf $(CACHE_DIR) $(CONFIG_DIR)
