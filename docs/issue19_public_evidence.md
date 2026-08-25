# Issue #19 public M0 evidence

The public evidence under
`.benchmarks/results/m0_issue19_public/20260822-sanitized-corrected-paired-10/`
is a deterministic sanitized export of the execution-node artifacts. The
original files remain unchanged in controlled local custody and are not part
of the public pull request history.

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

The recomputed result is:

- evidence valid: `10/10`;
- resource pathology: `1/10`;
- matched latency pathology: `0/10`;
- fixed reproduction gate: `8/10`;
- decision: `NO_GO`.

`correctness_100_percent=false` does not mean that the evidence is invalid.
An injected fault request is expected not to complete normally. The false
aggregate value records the one evidence-valid repetition with a resource
state-conservation failure; it prevents a universal correctness claim while
leaving the negative go/no-go decision evaluable.

No NPU run was repeated, no threshold or workload was changed, and lifecycle
reconciliation remains disabled.
