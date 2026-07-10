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
