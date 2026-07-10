CONDA ?= conda
CONDA_ENV ?= vllm-request-lifecycle-profiler-exp
CONDA_RUN ?= $(CONDA) run --no-capture-output -n $(CONDA_ENV)
PYTHON ?= $(CONDA_RUN) python
PIP ?= $(PYTHON) -m pip
PYTEST ?= PYTHONPATH=src $(PYTHON) -m pytest -q
RUFF ?= $(PYTHON) -m ruff
BUILD ?= $(PYTHON) -m build
SHARED_ENV_SCRIPT ?= /home/shuhao/llm-optimizations/scripts/bootstrap_shared_env.sh
SHARED_PROFILE ?= vllm-research
SHARED_ENV_NAME ?= $(CONDA_ENV)
WORKLOAD_REPO ?= $(abspath $(CURDIR)/third_party/llm-serving-workloads)

PACKAGE_IMPORT := vllm_request_lifecycle_profiler
BENCH_DIR := .benchmarks
PAPER_DIR := paper/request_lifecycle_causal_profiler

.DEFAULT_GOAL := help

.PHONY: help bootstrap-shared-env install-dev smoke test shared-workloads-smoke shared-workloads-test lint format build bench paper paper-assets paper-pdf paper-clean clean

help:
	@printf '%s\n' \
		'Default conda env: $(CONDA_ENV)' \
		'Common targets:' \
		'  make bootstrap-shared-env  Clone the shared vLLM baseline into the dedicated template env' \
		'  make install-dev  Install the package in editable mode with dev extras' \
		'  make smoke        Import-check the top-level package' \
		'  make test         Run the unit test suite' \
		'  make shared-workloads-smoke Run the repo-local shared workload compatibility sweep' \
		'  make shared-workloads-test  Run unit tests plus the shared workload compatibility sweep' \
		'  make lint         Run ruff checks' \
		'  make format       Run ruff formatting' \
		'  make build        Build sdist and wheel artifacts' \
		'  make bench        Show the benchmark workspace for this repo' \
		'  make paper        Show the paper workspace and local build entrypoint' \
		'  make paper-assets Refresh generated paper-facing assets from paper/results' \
		'  make paper-pdf    Build the paper scaffold PDF with tectonic' \
		'  make paper-clean  Remove local paper build outputs' \
		'  make clean        Remove common local build caches'

bootstrap-shared-env:
	$(SHARED_ENV_SCRIPT) --profile $(SHARED_PROFILE) --repo-root "$$PWD" --env-name '$(SHARED_ENV_NAME)'
	@$(MAKE) install-dev CONDA_ENV='$(SHARED_ENV_NAME)'
	@printf '%s\n' 'Bootstrap complete and dev dependencies installed.'

install-dev:
	@if [ -f '$(WORKLOAD_REPO)/pyproject.toml' ]; then \
		$(PIP) install -e '$(WORKLOAD_REPO)' || printf '%s\n' 'Skipping sibling llm-serving-workloads editable install; shared-workload entrypoints will use WORKLOAD_REPO/src directly.'; \
	else \
		printf 'Skipping sibling llm-serving-workloads install: %s\n' '$(WORKLOAD_REPO)'; \
	fi
	$(PIP) install -e ".[dev]"

smoke:
	PYTHONPATH=src $(PYTHON) -c "import importlib; importlib.import_module('$(PACKAGE_IMPORT)')"

test:
	$(PYTEST)

shared-workloads-smoke:
	@workload_src=''; \
	if [ -d '$(WORKLOAD_REPO)/src' ]; then \
		workload_src='$(WORKLOAD_REPO)/src'; \
	fi; \
	LLM_SERVING_WORKLOADS_SRC="$$workload_src" PYTHONPATH=src $(PYTHON) .benchmarks/run_shared_workloads_smoke.py \
		--output-json .benchmarks/results/shared_workloads_smoke.json \
		--output-markdown .benchmarks/results/shared_workloads_smoke.md

shared-workloads-test: test shared-workloads-smoke

lint:
	$(RUFF) check .

format:
	$(RUFF) format .

build:
	$(BUILD)

bench:
	@printf 'Benchmark assets: %s\n' '$(BENCH_DIR)'

paper:
	@printf '%s\n' \
		'Paper assets: $(PAPER_DIR)' \
		'Refresh derived assets with: make paper-assets' \
		'Build with: make paper-pdf'

paper-assets:
	$(MAKE) -C $(PAPER_DIR) paper-assets

paper-pdf:
	$(MAKE) -C $(PAPER_DIR) pdf

paper-clean:
	$(MAKE) -C $(PAPER_DIR) clean

clean:
	$(MAKE) -C $(PAPER_DIR) clean
	rm -rf build dist .pytest_cache .ruff_cache .mypy_cache .coverage
