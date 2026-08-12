# Pinned shared-workload ABI fixture

This fork-safe fixture exercises the narrow `llm_serving_workloads` API used by
the parent adapter when the private submodule cannot be exposed to an untrusted
pull-request runner. It is bound to gitlink
`76e24c85bcab76ecfabb831c9444002b6efffd58` and intentionally contains only a
minimal independent test implementation, not a copy of the private repository.

This gate proves parent-side API compatibility. It does not claim that the
private dependency's own test suite ran. A change to the gitlink or consumed
API must update this fixture under review and run the real shared-workload
suite in a trusted checkout.
