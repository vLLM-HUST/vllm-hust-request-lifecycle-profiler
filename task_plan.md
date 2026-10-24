# Request Lifecycle Profiler research plan

[Complete historical original](https://github.com/vLLM-HUST/vllm-hust-benchmark/blob/c45a279dd2ee48c57a7cb27a0d7ad0666f25afd5/archive/mod-targeted-20261023/profiler-notes/snapshot/task_plan.md).
[Evidence and consumer map](docs/notes_evidence.md) distinguishes immutable
historical records, current methods and missing local artifacts. This page
does not claim a new experiment, build, visual review or device admission.

## Goal

Move from probe/readiness evidence toward controlled causal evidence without
overstating synthetic, existing-server or derived results. Current sequence:
[next_agent_task.md](docs/next_agent_task.md); status: `NOT_M0_PROVEN`.

## Source and artifact ownership

- This repository owns maintained scripts, methods, schemas, synthetic fixtures
  and source/dependency pointers. Historical measurements and generated paper
  outputs belong in benchmark, as indexed in [EVIDENCE.md](EVIDENCE.md).
- Preserve unrelated worktree changes; do not reset, clean or revert them.
- Keep runtime changes in the appropriate repository and feature branch.
- Keep diagnostic and formal execution modes distinct, and record actual
  provenance. Apply the current benchmark protocol rather than interpreting an
  old planning note as an additional acceptance rule.
- Never kill unrelated processes, switch hardware silently or overwrite
  downloaded archival inputs. New outputs need separate run-owned locations.

## Historical phases and errors

The original completed-phase table, numeric observations, test/build/visual
checks and error table are retained verbatim at the original link above.
They are historical receipts, not a current queue or current-main test result.
The associated [progress](progress.md) and [findings](findings.md) remain
stable navigation entries. Current validity and missing-input boundaries are
in [the evidence map](docs/notes_evidence.md) and [claim ledger](docs/claim_ledger.md).
No new device experiment or paper rebuild is implied by this migration.
