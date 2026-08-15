# Pinned shared-workload ABI fixture

This fork-safe fixture exercises only the narrow `llm_serving_workloads` API
consumed by the parent adapter when an untrusted pull-request runner cannot
access the pinned workload submodule. It is associated with gitlink
`76e24c85bcab76ecfabb831c9444002b6efffd58`.

The implementation below was written independently for tests; it is not a
copy of the dependency and contains no workload data. This check proves only
parent-side API compatibility. It does not claim that the dependency's own
test suite ran. A change to the gitlink or consumed API requires reviewing and
updating this fixture and running the real workload suite in a trusted checkout.
