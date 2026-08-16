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
zero-loss close exposes `committed_shard_path`; Route B still requires the
separate exact-C1 validation receipt before manifest admission.

## API boundary

The parent exporter owns cycle/batch/step/sample sequences and canonical local
IDs. PR-I2 supplies audited observations through:

- `begin_cycle`;
- `write_logical_batch`;
- `write_execution_step_start`;
- `write_execution_step_end`; and
- `write_clock_bridge_sample`.

Construction and producer failures remain serving-fail-open. Serialization,
queue, writer, control-record, or close failures remain evidence-fail-closed.
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
