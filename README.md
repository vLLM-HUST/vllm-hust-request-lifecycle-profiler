# Request Lifecycle Causal Profiler

This repository is an incubation optimization/artifact line for causal request
lifecycle tracing in LLM serving. It targets a single-NPU first implementation
on NPU6 and follows the same optimization-repository workflow as the other
repositories in the `llm-optimizations` workspace.

Start with:

- [PROJECT_BRIEF.md](PROJECT_BRIEF.md) for the research question, mechanism,
  evidence path, and NPU binding;
- [TOP_TIER_PUSH_PLAN.md](TOP_TIER_PUSH_PLAN.md) for the first 72-hour ASPLOS
  push plan;
- `llm-serving-workloads` as the shared workload source.

Do not install project overlays into the shared `vllm-hust-dev` environment.
Clone it into `vllm-request-lifecycle-profiler-exp` or use the repository
bootstrap target.

## Bootstrap

Preferred bootstrap:

```bash
make bootstrap-shared-env
```

That clones the shared `vllm-research` baseline into a dedicated template env
and installs the template repository as the repo overlay.

This repository is a minimal standalone template for building an independently
publishable vLLM optimization plugin.

It is intended for the exact workflow you asked about:

- keep the optimization in its own repository,
- publish it as a normal Python package,
- install it into a target vLLM environment, and
- inject it into vLLM through the official plugin mechanism instead of carrying
  a long-lived fork.

It also now carries the minimum workload-driven test skeleton needed for future
derived repositories to start their full shared-workload test flow from the
sibling `llm-serving-workloads` repository.

## Upstream Safety Workflow

- Keep the shared external `reference-repos/vllm` checkout clean.
- Use this template to build out-of-tree plugins, not to justify patching the reference checkout.
- If a derived plugin truly needs upstream-local code, vendor or clone vLLM inside that derived repository.

## Workflow Compliance For Derived Repositories

Repositories created from this template should follow the optimization
repository workflow from day one:

- Treat the derived repository as the parent artifact for plugin code,
  experiments, paper assets, and reproducibility docs.
- Keep runtime dependencies as repo-local vendored checkouts, submodules, or
  explicit patches; never rely on a shared external vLLM checkout for a paper
  claim.
- Use a project-specific conda environment for real runs and project overlays.
- If a runtime submodule needs edits, use a `feature/<project>-<purpose>`
  branch, not `main` and not a `codex/...` branch.
- Label result evidence as `real-online`, `existing-server-probe`, `replay`,
  `simulation/model`, `projected-profile`, or `derived-artifact`.
- Every benchmark output directory should include manifest/provenance metadata
  for parent commit, dependency commits, dirty status, hardware, model,
  environment, command, workload, and timestamp.

## Why This Works

vLLM already supports general plugins through Python entry points under the
group `vllm.general_plugins`, filtered by the `VLLM_PLUGINS` environment
variable and loaded through `vllm.plugins.load_general_plugins()`.

That means an optimization plugin can be distributed out of tree as long as it:

1. registers a callable entry point,
2. keeps the registration logic re-entrant, and
3. patches or extends a stable-enough runtime boundary in the target vLLM
   version.

## Repository Layout

```text
vllm-request-lifecycle-profiler-plugin/
├── .benchmarks/
│   ├── README.md
│   └── run_shared_workloads_smoke.py
├── CHANGELOG.md
├── CONTRIBUTING.md
├── Makefile
├── README.md
├── scripts/
│   └── render_placeholder_paper_scaffold.py
├── paper/
  │   ├── README.md
  │   └── request_lifecycle_causal_profiler/
  │       ├── experiments/
  │       │   ├── README.md
  │       │   └── export_paper_assets.py
  │       ├── figures/
  │       │   └── README.md
  │       ├── Makefile
  │       ├── references.bib
  │       ├── results/
  │       │   ├── README.md
  │       │   ├── example_live/
  │       │   │   └── README.md
  │       │   └── example_metrics.json
  │       ├── request_lifecycle_causal_profiler.tex
  │       └── tables/
  │           ├── README.md
  │           └── manual/
  │               └── README.md
├── pyproject.toml
├── src/
│   └── vllm_request_lifecycle_profiler/
│       ├── __init__.py
│       ├── launcher.py
│       ├── plugin.py
│       └── shared_workloads.py
└── tests/
  ├── test_launcher.py
  └── test_shared_workloads.py
```

This is intentionally lighter than `sglang-dp-locality-plugin`, but it now
teaches the same root-level separation of package code, tests, benchmark
entrypoints, and a paper workspace that can already emit a local PDF through a
repo-local tectonic Makefile.

## Installation

```bash
make bootstrap-shared-env
make install-dev
```

`make install-dev` now also installs the sibling `llm-serving-workloads`
package when it exists, so shared-workload smoke tests resolve the shared case
catalog from the workspace by default.

## Common Local Commands

```bash
make help
make smoke
make test
make shared-workloads-smoke
make shared-workloads-test
make paper-assets
make paper-pdf
make lint
make format
make build
```

## Shared Workload Convention

Future repositories derived from this template should keep these target names so
they can be driven from `llm-serving-workloads` and `llm-optimizations`
automatically:

- `test`: unit and package-local tests
from `llm-serving-workloads` through `LLM_SERVING_WORKLOADS_SRC`, the sibling
workspace checkout, or an installed package. It intentionally skips public-only
boundary cases such as `sharegpt` that require external data or runtime setup.

From the workload repository, the generic wrapper path is:

  MANAGED_PLUGIN_REPO=/path/to/vllm-request-lifecycle-profiler-plugin
```

Any future optimization repository created from this template can keep that same
entry contract and replace only the plugin/package names.

## Paper Scaffold

The template now carries a minimal paper artifact scaffold under
`paper/request_lifecycle_causal_profiler/`.

That scaffold is intentionally generic rather than policy-specific. It gives a
new repository three things on day one:

- a checked-in LaTeX draft that states the artifact boundary honestly,
- a repo-local `tectonic` Makefile for PDF builds, and
- a bibliography file that derived repositories can extend instead of creating
  paper build plumbing from scratch.

It now also carries the minimum paper-side directory convention that mature
artifact repos keep converging toward:

- `paper/<topic>/experiments/` for paper-only export or plotting helpers,
- `paper/<topic>/results/` for raw or intermediate offline outputs consumed by
  the paper build,
- `paper/<topic>/results/example_live/` for live-serving or online results that
  should remain separate from the offline result bucket,
- `paper/<topic>/figures/` for stable figure paths used by LaTeX, and
- `paper/<topic>/tables/` for hand-written or generated table snippets, with
  `tables/manual/` reserved for curated non-generated tables.

The generic `make paper-assets` path now refreshes derived paper-facing assets
from `paper/request_lifecycle_causal_profiler/results/` before PDF compilation. In the
template, that means:

- scanning both `results/` and `results/example_live/`,
- generating a manifest of available result files,
- generating a Markdown summary for humans, and
- generating a LaTeX snippet under `tables/generated/` that the paper draft can
  input automatically.

The export-script interface is now closer to the mature repos in this
workspace. The template path accepts explicit `results-dir`,
`live-results-dir`, `output-dir`, `figure-dir`, and `table-dir` arguments, so
derived repositories can keep the same high-level contract even after replacing
the generic export logic with project-specific figure and table generation.

Build the placeholder paper locally with:

```bash
make paper-assets
make paper-pdf
```

Or invoke the paper workspace directly:

```bash
make -C paper/request_lifecycle_causal_profiler paper-assets
make -C paper/request_lifecycle_causal_profiler pdf
```

For repositories that were not originally created from this template but still
need a truthful placeholder manuscript, the same single-repo scaffold is also
## Reference Paper

- Short label: `Hardware-Conscious SP Survey / SIGMOD Record 2020`
- Full paper: `Hardware-Conscious Stream Processing: A Survey`

Chinese guidance for student follow-up:

- 学这篇的地方：把 template 看成设计空间和优化检查表的承载体，帮助派生仓库明确问题分层、硬件约束和可验证的系统边界。
- 不要直接照搬的地方：这篇 survey 回顾的是 hardware-conscious stream processing；当前仓库是 vLLM 独立插件模板，不应该绑定到某一个具体优化方法或结论。
- 写作时更适合继承的是：如何组织 design dimensions、如何提醒派生仓库显式说明 tradeoff 和 evidence boundary、以及如何保持模板本身的中立和可复用性。
exposed through:

```bash
python3 scripts/render_placeholder_paper_scaffold.py \
  --repo-root /path/to/repo \
  --paper-subdir paper/<topic> \
  --paper-slug <topic> \
  --title "<paper title>" \
  --problem-frame "<bounded problem frame>" \
  --artifact-boundary "<truthful current boundary>"
```

That keeps the placeholder paper text and Makefile contract owned by the
template repository. Workspace-level scripts can call this renderer in batch,
but they no longer need to embed the template content themselves.

## Usage

With explicit plugin loading:

```bash
VLLM_PLUGINS=request_lifecycle_profiler \
vllm serve --model <model>
```

Or through the wrapper launcher:

```bash
vllm-request-lifecycle-profiler-serve serve --model <model>
```

## What To Change For A Real Optimization

- Rename the package and plugin name in `pyproject.toml`.
- Replace the sample patch in `plugin.py` with your real optimization hook.
- Rename `paper/request_lifecycle_causal_profiler/` to the derived repository's paper
  topic, then replace the placeholder manuscript with the actual problem
  framing, artifact boundary, and measured results.
- Keep the `experiments/`, `results/`, `figures/`, and `tables/` layout under
  that paper topic unless the paper truly has no experiment-facing assets.
- Keep `results/example_live/` when the repo has any online or serving-side
  measurements; that split avoids mixing offline probes with live runs.
- Keep `tables/manual/` for hand-maintained tables that should not be
  overwritten by export scripts.
- Replace the generic `experiments/export_paper_assets.py` logic with the
  repository's real figure/table export path once measured results exist, but
  keep the `paper-assets -> pdf` contract stable.
- Keep the standard workload-driven targets and update their internals rather
  than deleting them, so the derived repository still participates in the
  workspace-level `llm-serving-workloads -> plugin` test convention.
- Keep the patch idempotent because vLLM may load plugins in multiple
  processes.
- Prefer narrow monkey-patch boundaries such as one scheduler method, one
  attention-layer path, or one model registration hook.

## Good Fit For This Pattern

- decode backend selection
- scheduler admission control
- KV pressure control
- out-of-tree model registration
- instrumentation and observability hooks
- targeted runtime fast paths

## Weak Fit For This Pattern

- changes that require deep custom kernels inside vLLM C++ or Triton internals
- changes that need broad cross-module refactors in upstream runtime logic
- features that depend on undocumented internals with high churn risk

## Publishing Flow

```bash
python -m build --sdist --wheel
pip install dist/vllm_request_lifecycle_profiler-*.whl
```

Then load it in the target vLLM environment:

```bash
VLLM_PLUGINS=request_lifecycle_profiler vllm serve --model <model>
```

## Generic dev-hub Validation

Use this pattern to validate this plugin through the host-managed vLLM-HUST dev-hub launcher. Keep dev-hub generic: do not hardcode this repository name, plugin name, port, NPU IDs, or experiment container in dev-hub itself.

Before launch:

- confirm this repository is visible inside the container, usually under `/workspace/<repo-name>`;
- check NPU occupancy with `npu-smi info`;
- choose a unique experiment container name, systemd unit name, and free port;
- use a real API key already configured for the manager, but never print or record it;
- do not share the active twin container.

Generic launch template:

```bash
export DEV_HUB_ROOT=${DEV_HUB_ROOT:-/home/shuhao/vllm-hust-dev-hub}

export VLLM_ENGINE_CONTAINER=<unique-experiment-container>
export VLLM_ENGINE_IMAGE=<known-good-vllm-ascend-image>
export VLLM_ENGINE_AUTO_CREATE_CONTAINER=true
export VLLM_ENGINE_MODEL_PATH=<model-path>
export VLLM_ENGINE_SERVED_MODEL_NAME=<served-model-name>
export VLLM_ENGINE_CONDA_ENV=<conda-env>
export VLLM_ENGINE_PORT=<free-port>
export VLLM_ENGINE_TP_SIZE=<tp-size>
export VLLM_ENGINE_NPU_DEVICES=<dedicated-npu-ids>
export VLLM_ENGINE_SYSTEMD_UNIT=<unique-unit-name>.service
export VLLM_ENGINE_COMPILATION_CONFIG='<optional-json-compilation-config>'

export VLLM_PLUGINS=<plugin-name-or-comma-list>
export VLLM_ENGINE_PYTHONPATH=/workspace/<repo-name>/src:/workspace/<repo-name>:/workspace/vllm-hust:/workspace/vllm-ascend-hust

"$DEV_HUB_ROOT/manage.sh" restart
"$DEV_HUB_ROOT/manage.sh" status --json
```

Run A/B with only plugin-owned environment variables changed between baseline and experiment. Record command shape, devices, model, graph config, prompt, max tokens, output length, TTFT, TPOT, throughput, result paths, confirmed facts, hypotheses, rejected directions, and the next experiment. If startup fails, stop through the same manager and record the failure; do not switch to manual Docker startup.
