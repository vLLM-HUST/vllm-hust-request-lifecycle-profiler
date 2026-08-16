# Scheduler profiler PR-I1 exporter

Status: implementation candidate

PR-I1 implements the parent-repository writer for the frozen
`rlp.scheduler/v1alpha1` Route-B wire. It deliberately does not patch or import
vLLM scheduler, EngineCore, worker, or model-runner call sites; those adapters
remain PR-I2 work.

## Process-local ownership

`ProcessLocalExporterIdentity` carries the launcher-provided
`process_instance_id`, clock domain, and owner PID. Lifecycle and scheduler
exporters may consume that same identity, while each stream retains an
independent file, writer thread, queue, data sequence, loss ledger, content
digest, summary, and close result.

The scheduler shard path is:

```text
<base>.rlp-scheduler.<scheduler_shard_id>.jsonl
```

It is created exclusively with mode `0600`. Only a drained, summary-written,
zero-loss, whole-run-valid close exposes `committed_shard_path`; Route B still
requires the separate exact-C1 validation receipt before manifest admission.

The writer reserves the formal path and writes through a private incomplete
path. A single immutable close claim publishes the completed shard atomically.
If a close timeout wins while a summary write is still in flight, the late
bytes remain incomplete and cannot replace the timeout result or become a
committed shard.

## Whole-run admission ownership

PR-I1 chooses producer-owned enforcement rather than deferring bounds to
PR-I2 or the launcher. Before opening a shard it requires the frozen free-disk
admission. During production it enforces formal duration, total cycle count,
rolling cycle rate, total clock-bridge samples, cumulative artifact bytes, and
the total number of materialized loss intervals.

The first violation enters a permanent formal-invalid state. Serving calls
continue and return without blocking, but the exporter stops materializing new
data. A close may retain a diagnostic shard; its close result carries the
stable invalid reason and can never expose a committed shard. Once 64 loss
intervals have been materialized, a later disjoint loss is left unmaterialized
and permanently invalidates formal evidence rather than exceeding the C1
artifact proof.

`SchedulerCloseResult.writer_complete` means only that the local writer
drained, wrote its summary, and transported every attempted record without a
writer, loss, or whole-run admission failure. It is not C1 semantic
validation. The admission rule is:

```text
route_b_admissible =
    writer_complete
    and exact_c1_scheduler_validation_receipt_valid
```

## API boundary

The parent exporter owns cycle/batch/step/sample sequences and canonical local
IDs. PR-I2 supplies audited observations through:

- `begin_cycle`;
- `write_logical_batch`;
- `write_execution_step_start`;
- `write_execution_step_end`; and
- `write_clock_bridge_sample`.

Construction and producer failures remain serving-fail-open. Serialization,
queue, whole-run admission, writer, control-record, or close failures remain
evidence-fail-closed.
When disabled, the factory creates no identity, clock sample, queue, thread,
ID, or file.

## Validation

```bash
PYTHONPATH=src python -m pytest -q \
  tests/test_scheduler_profile_contract.py \
  tests/test_scheduler_profile_exporter.py
```

The exporter test feeds a completed shard back through the standalone C1
verifier and separately tests shared process identity, independent stream
sequences, queue-loss accounting, writer-failure isolation, and default-off
behavior.
