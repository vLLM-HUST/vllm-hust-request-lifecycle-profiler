# Issue #19 public M0 evidence

Historical observations and the complete pre-migration text: [benchmark original](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/842fc4bc69978e50e3b776731a962bfcf33ffaf3/archive/mod-targeted-20261023/profiler-protocols/snapshot/docs/issue19_public_evidence.md).
[Evidence and consumer map](protocol_evidence.md) distinguishes archived members,
unrecovered inputs and newly generated outputs. Protocol values are not new measurements.

The public evidence under
`.benchmarks/results/m0_issue19_public/20260822-sanitized-corrected-paired-10/`
is a deterministic sanitized export of the execution-node artifacts. The
original files remain unchanged in controlled local custody and are not part
of the public pull request history.

The public export has moved to [canonical benchmark custody](../EVIDENCE.md).
The path above is now relative to the verified external `BENCHMARK_EVIDENCE_ROOT`,
not this source checkout. Download it and export that variable before the Make
verification below. The unchanged NO_GO assertion still verifies every public file.

## Boundary

The exporter retains all ten matched fault/control analyses, client results,
request/resource traces, failure witnesses, lifecycle snapshots, event
ordering, monotonic timestamps, and numeric measurements. It replaces machine
paths, private or loopback addresses, the service port, NPU identifiers, PIDs,
PCI identifiers, and the boot-derived clock-domain identifier with stable
placeholders. Request/run identities and clock-domain equality relationships
remain intact without exposing the execution node's boot fingerprint.

Raw `server.log` files and complete `npu-smi` before/during/after snapshots are
withheld because they contain execution-node and unrelated-process topology.
Their original sizes and SHA-256 values remain in `redaction_manifest.json` so
the controlled source can be identified without publishing its contents. This
is an ordinary integrity record requested for this public-artifact review; it
is not an approval, freeze, or co-signature mechanism.

## Reproduce the public export

With the original custody directory available locally:

```bash
PYTHONPATH=src python -m \
  vllm_request_lifecycle_profiler.issue19_public_artifacts export \
  --source "$RAW_CUSTODY" \
  --output "$PUBLIC_EXPORT" \
  --custody-manifest "$LOCAL_CUSTODY_MANIFEST"
```

Verify every published file hash, scan the export boundary, and recompute the
aggregate decision from the sanitized per-arm analyses:

```bash
make issue19-public-evidence-verify
```

The historical numerical decision and per-arm measurements are preserved in
the linked benchmark original and verified public capsule. The command above
recomputes from those inputs; this page does not maintain a duplicate score table.

## Scientific decision and scope

This is an evidence-valid mechanism `NO_GO`, not an invalid or incomplete
experiment. Its scope is exactly the preregistered specialty experiment:

- worker exit is the final injected action after a witnessed pending transfer;
- the owned Worker generation is terminated and the service is shut down;
- Qwen2.5-14B-Instruct, the fixed OASST1 projection and request order, TP=1,
  `max_model_len=10880`, 2 GiB device KV-cache capacity, and 8 GiB CPU offload
  capacity remain fixed;
- `lifecycle_reconcile=false`; and
- the resource and matched-latency reproduction gate remains `8/10`.

The result supports only this statement: the fixed scenario does not provide
enough repeatable resource or latency pathology to justify implementing or
enabling the proposed lifecycle reconciliation treatment. It does not show
that lifecycle failures, reconciliation, or request-scoped diagnosis are
generally ineffective. In particular, it does not cover distinct disconnect,
timeout, connector-receipt-loss, multi-Worker, or multi-rank hypotheses.

## Decision-gate interpretation

Issue #19 is retained as a negative decision-impact case:

1. request and resource evidence remained complete during a real Worker fault;
2. the evaluator distinguished expected fault noncompletion, invalid evidence,
   and a state-conservation failure;
3. an evidence-valid resource conservation failure was retained rather than hidden;
4. the measured reproduction did not reach the fixed gate; and
5. the preregistered gate therefore stopped an unsupported treatment instead
   of allowing post-hoc threshold, workload, or capacity changes.

The durable claim boundary is:

> Issue #19 mechanism `NO_GO` is not Request Lifecycle topic `NO_GO`.

Complete capture proves evidence availability, not causal root cause. A long
stage can localize an interval, but a mechanism claim still requires matched
evidence, uncertainty/residual reporting, and a validating counterfactual.

`correctness_100_percent=false` does not mean that the evidence is invalid.
An injected fault request is expected not to complete normally. The false
aggregate value records an evidence-valid resource
state-conservation failure; it prevents a universal correctness claim while
leaving the negative go/no-go decision evaluable.

No NPU run was repeated, no threshold or workload was changed, and lifecycle
reconciliation remains disabled.

Any future experiment on a different lifecycle boundary must use a separate
research question, preregistration, and stopping condition. It must preserve,
rather than reinterpret, this fixed negative result.
