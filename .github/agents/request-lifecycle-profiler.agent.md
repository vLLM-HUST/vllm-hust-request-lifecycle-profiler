# request-lifecycle-profiler.agent

Use this agent when working in `vllm-request-lifecycle-profiler-plugin` on:

- lifecycle trace schemas;
- causal bottleneck attribution;
- controlled fault-injection probes;
- claim ledgers for diagnosis artifacts.

## Hard Boundary

- Use NPU6 unless the coordinator explicitly reassigns the project.
- Use `vllm-request-lifecycle-profiler-exp`, not the shared `vllm-hust-dev` env.
- Keep profiler-only evidence separate from runtime policy improvements.
- Use the pinned `third_party/llm-serving-workloads` submodule for shared
  workloads and record its commit in every manifest.
- Follow `docs/next_agent_task.md` before starting NPU6 experiments.
