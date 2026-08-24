CONDA ?= conda
CONDA_ENV ?= vllm-request-lifecycle-profiler-exp
CONDA_ENV_PREFIX ?= /home/shuhao/miniconda3/envs/$(CONDA_ENV)
PYTHON ?= $(CONDA_ENV_PREFIX)/bin/python
PIP ?= $(PYTHON) -m pip
PYTEST ?= PYTHONPATH=src $(PYTHON) -m pytest -q
RUFF ?= $(PYTHON) -m ruff
BUILD ?= $(PYTHON) -m build
LINT_TARGETS ?= src tests .benchmarks scripts paper/request_lifecycle_causal_profiler/experiments
SHARED_ENV_SCRIPT ?= /home/shuhao/llm-optimizations/scripts/bootstrap_shared_env.sh
SHARED_PROFILE ?= vllm-research
SHARED_ENV_NAME ?= $(CONDA_ENV)
WORKLOAD_REPO ?= $(abspath $(CURDIR)/third_party/llm-serving-workloads)
DEV_HUB ?= $(abspath $(CURDIR)/third_party/vllm-hust-dev-hub)
MANAGED_ENV_FILE ?= $(abspath $(CURDIR)/.benchmarks/profiles/npu6_vllm_hust_trace.env)
TRACE_SUITE_OUTPUT_DIR ?= .benchmarks/results/npu6_existing_server_trace_probe_repeated_smoke
ISSUE19_RUNTIME_PYTHON ?= $(abspath $(CURDIR)/.venv-issue19/bin/python)

PACKAGE_IMPORT := vllm_request_lifecycle_profiler
BENCH_DIR := .benchmarks
PAPER_DIR := paper/request_lifecycle_causal_profiler

.DEFAULT_GOAL := help

.PHONY: help bootstrap-shared-env install-dev smoke test shared-workloads-smoke shared-workloads-test issue19-m0-preflight issue19-public-evidence-verify offline-intervention-gate synthetic-fault-injection trace-diagnosis npu6-controlled-fault-matrix npu6-runtime-hook-pair-plan npu6-runtime-concurrency-anomaly-analysis top-tier-readiness npu6-trace-preflight npu6-existing-server-trace-probe npu6-existing-server-trace-suite-smoke npu6-existing-server-slow-stream-trace-smoke npu6-slow-stream-trace-diagnosis npu6-existing-server-trace-overhead-smoke managed-install managed-start managed-restart managed-stop managed-status managed-health managed-logs managed-foreground lint format build bench paper paper-assets paper-pdf paper-clean clean

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
		'  make issue19-m0-preflight Build the fixed six-path plan and fail-closed serving readiness report' \
		'  make issue19-public-evidence-verify Verify the sanitized matched-M0 export and recompute its decision' \
		'  make offline-intervention-gate Evaluate the CPU-only matched-intervention fixture' \
		'  make synthetic-fault-injection Run no-NPU controlled lifecycle attribution checks' \
		'  make trace-diagnosis Derive client-visible stage diagnosis from checked-in NPU6 trace probe' \
		'  make npu6-controlled-fault-matrix Aggregate checked-in NPU6 controlled-fault artifacts and gaps' \
		'  make npu6-runtime-hook-pair-plan Aggregate or list hook-disabled/enabled runtime probe runs' \
		'  make npu6-runtime-concurrency-anomaly-analysis Analyze checked-in NPU6 concurrency runtime-hook anomaly' \
		'  make top-tier-readiness Run no-NPU checks and refresh submission-facing artifacts' \
		'  make npu6-trace-preflight Run read-only NPU6 existing-server trace preflight' \
		'  make npu6-existing-server-trace-probe Run client-observed lifecycle trace probe on NPU6' \
		'  make npu6-existing-server-trace-suite-smoke Run warmup-controlled repeated trace suite on NPU6' \
		'  make npu6-existing-server-slow-stream-trace-smoke Run client-visible slow-stream trace probe on NPU6' \
		'  make npu6-slow-stream-trace-diagnosis Derive diagnosis from the slow-stream trace probe' \
		'  make npu6-existing-server-trace-overhead-smoke Run matched no-trace/trace client-probe overhead suite on NPU6' \
		'  make managed-start Start the NPU6 baseline through vLLM-HUST dev-hub using the repo profile' \
		'  make managed-stop  Stop the managed NPU6 baseline service' \
		'  make managed-health Check managed service /health through dev-hub' \
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

issue19-m0-preflight:
	PYTHONPATH=src $(ISSUE19_RUNTIME_PYTHON) -m vllm_request_lifecycle_profiler.issue19_m0 \
		--runtime-python $(ISSUE19_RUNTIME_PYTHON) \
		--model-path /root/.cache/huggingface/hub/models--Qwen--Qwen2.5-14B-Instruct/snapshots/cf98f3b3bbb457ad9e2bb7baf9a0125b6b88caa8 \
		--output-dir .benchmarks/results/m0_issue19_preflight

issue19-public-evidence-verify:
	PYTHONPATH=src $(ISSUE19_RUNTIME_PYTHON) -m vllm_request_lifecycle_profiler.issue19_public_artifacts verify \
		--public-root .benchmarks/results/m0_issue19_public/20260822-sanitized-corrected-paired-10

offline-intervention-gate:
	PYTHONPATH=src $(PYTHON) .benchmarks/evaluate_offline_intervention_fixture.py

synthetic-fault-injection:
	PYTHONPATH=src $(PYTHON) .benchmarks/run_synthetic_fault_injection.py \
		--output-dir .benchmarks/results/synthetic_fault_injection

trace-diagnosis:
	PYTHONPATH=src $(PYTHON) .benchmarks/analyze_trace_diagnosis.py \
		--input-probe-results .benchmarks/results/npu6_existing_server_trace_probe_repeated_smoke/probe_results.json \
		--output-dir .benchmarks/results/npu6_trace_diagnosis

npu6-controlled-fault-matrix:
	PYTHONPATH=src $(PYTHON) .benchmarks/analyze_controlled_fault_matrix.py

npu6-runtime-hook-pair-plan:
	PYTHONPATH=src $(PYTHON) .benchmarks/run_runtime_hook_pair_plan.py

npu6-runtime-concurrency-anomaly-analysis:
	PYTHONPATH=src $(PYTHON) .benchmarks/analyze_runtime_concurrency_anomaly.py

top-tier-readiness: test synthetic-fault-injection trace-diagnosis npu6-controlled-fault-matrix npu6-runtime-hook-pair-plan npu6-runtime-concurrency-anomaly-analysis paper-assets
	@PYTHONPATH=src $(PYTHON) -c "import json, pathlib, sys; p=pathlib.Path('.benchmarks/results/npu6_runtime_hook_pair_plan/summary.json'); data=json.loads(p.read_text()); rows=data.get('rows', []); enabled=next((r for r in rows if r.get('mode') == 'hook-enabled'), {}); summary=enabled.get('runtime_trace_summary') or {}; complete=summary.get('complete_chain_count', 0); total=summary.get('request_chain_count', 0); missing=summary.get('missing_stage_counts', {}); print({'runtime_hook_complete_chains': complete, 'runtime_hook_total_chains': total, 'missing_stage_counts': missing}); sys.exit(0 if total and complete == total and not missing else 1)"
	@PYTHONPATH=src $(PYTHON) -c "import json, pathlib, sys; p=pathlib.Path('.benchmarks/results/npu6_runtime_hooks_concurrency_sweep/concurrency_anomaly_analysis/summary.json'); data=json.loads(p.read_text()); diagnosis=data.get('diagnosis', {}); requirements=data.get('required_subprefill_instrumentation', []); status={'prefill_outlier_count': data.get('prefill_outlier_count'), 'prefill_outlier_concurrency_values': data.get('prefill_outlier_concurrency_values'), 'stage_localization': diagnosis.get('stage_localization'), 'root_cause_status': diagnosis.get('root_cause_status'), 'missing_instrumentation_components': [row.get('component') for row in requirements if row.get('status') == 'missing']}; print(status); sys.exit(0 if data.get('prefill_outlier_count', 0) > 0 and data.get('prefill_outlier_concurrency_values') == [2] and diagnosis.get('stage_localization') == 'prefill' and diagnosis.get('root_cause_status') == 'unresolved' and len(status['missing_instrumentation_components']) == 4 else 1)"
	@PYTHONPATH=src $(PYTHON) -c "import json, pathlib, sys; p=pathlib.Path('.benchmarks/results/npu6_controlled_fault_matrix/summary.json'); data=json.loads(p.read_text()); status={'available_case_count': data.get('available_case_count'), 'missing_classes': data.get('missing_classes'), 'real_online_matrix_status': data.get('real_online_matrix_status')}; print(status); sys.exit(0 if data.get('available_case_count', 0) >= 4 and set(data.get('missing_classes', [])) == {'queue_pressure', 'kv_pressure', 'cleanup_stall'} and data.get('real_online_matrix_status') == 'incomplete' else 1)"

npu6-trace-preflight:
	ASCEND_HOME_PATH=/usr/local/Ascend PYTHONPATH=src $(PYTHON) .benchmarks/preflight_npu6_trace_probe.py \
		--endpoint http://127.0.0.1:18168 \
		--model-path /data/shared_models/Qwen2.5-7B-Instruct \
		--trace-export-path /tmp/codex-vllm-request-lifecycle-profiler-npu6-trace.jsonl \
		--api-token-env VLLM_HUST_API_KEY \
		--output-dir .benchmarks/results/npu6_trace_probe_preflight

npu6-existing-server-trace-probe:
	PYTHONPATH=src $(PYTHON) .benchmarks/run_existing_server_trace_probe.py \
		--endpoint http://127.0.0.1:18168 \
		--model codex-qwen2.5-7b-npu6 \
		--api-key-env VLLM_HUST_API_KEY \
		--trace-export-path /tmp/codex-vllm-request-lifecycle-profiler-npu6-trace.jsonl \
		--output-dir .benchmarks/results/npu6_existing_server_trace_probe_smoke

npu6-existing-server-trace-suite-smoke:
	PYTHONPATH=src $(PYTHON) .benchmarks/run_existing_server_trace_probe.py \
		--endpoint http://127.0.0.1:18168 \
		--model codex-qwen2.5-7b-npu6 \
		--api-key-env VLLM_HUST_API_KEY \
		--warmup-requests 1 \
		--repeat-count 3 \
		--max-requests 4 \
		--trace-export-path /tmp/codex-vllm-request-lifecycle-profiler-npu6-trace.jsonl \
		--output-dir $(TRACE_SUITE_OUTPUT_DIR)

npu6-existing-server-slow-stream-trace-smoke:
	PYTHONPATH=src $(PYTHON) .benchmarks/run_existing_server_trace_probe.py \
		--endpoint http://127.0.0.1:18168 \
		--model codex-qwen2.5-7b-npu6 \
		--api-key-env VLLM_HUST_API_KEY \
		--warmup-requests 1 \
		--repeat-count 2 \
		--max-requests 2 \
		--request-max-tokens 64 \
		--per-chunk-read-delay-ms 80 \
		--proxy-stage-mode streaming-proxy \
		--trace-export-path /tmp/codex-vllm-request-lifecycle-profiler-npu6-slow-stream-trace.jsonl \
		--output-dir .benchmarks/results/npu6_existing_server_slow_stream_trace_smoke

npu6-slow-stream-trace-diagnosis:
	PYTHONPATH=src $(PYTHON) .benchmarks/analyze_trace_diagnosis.py \
		--input-probe-results .benchmarks/results/npu6_existing_server_slow_stream_trace_smoke/probe_results.json \
		--output-dir .benchmarks/results/npu6_slow_stream_trace_diagnosis

npu6-existing-server-trace-overhead-smoke:
	PYTHONPATH=src $(PYTHON) .benchmarks/run_existing_server_trace_overhead_suite.py \
		--endpoint http://127.0.0.1:18168 \
		--model codex-qwen2.5-7b-npu6 \
		--api-key-env VLLM_HUST_API_KEY \
		--warmup-requests 1 \
		--repeat-count 3 \
		--max-requests 4 \
		--output-dir .benchmarks/results/npu6_existing_server_trace_overhead_smoke

managed-install:
	VLLM_ENGINE_ENV_FILE='$(MANAGED_ENV_FILE)' '$(DEV_HUB)'/manage.sh install

managed-start:
	VLLM_ENGINE_ENV_FILE='$(MANAGED_ENV_FILE)' '$(DEV_HUB)'/manage.sh start

managed-restart:
	VLLM_ENGINE_ENV_FILE='$(MANAGED_ENV_FILE)' '$(DEV_HUB)'/manage.sh restart

managed-stop:
	VLLM_ENGINE_ENV_FILE='$(MANAGED_ENV_FILE)' '$(DEV_HUB)'/manage.sh stop

managed-status:
	VLLM_ENGINE_ENV_FILE='$(MANAGED_ENV_FILE)' '$(DEV_HUB)'/manage.sh status

managed-health:
	VLLM_ENGINE_ENV_FILE='$(MANAGED_ENV_FILE)' '$(DEV_HUB)'/manage.sh health

managed-logs:
	VLLM_ENGINE_ENV_FILE='$(MANAGED_ENV_FILE)' '$(DEV_HUB)'/manage.sh logs

managed-foreground:
	VLLM_ENGINE_ENV_FILE='$(MANAGED_ENV_FILE)' '$(DEV_HUB)'/manage.sh foreground

lint:
	$(RUFF) check $(LINT_TARGETS)

format:
	$(RUFF) format $(LINT_TARGETS)

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
