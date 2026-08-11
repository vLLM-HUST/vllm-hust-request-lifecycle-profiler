"""G1 CPU controlled-trace seal workflow.

Drives the real OffloadingConnector scheduler/worker through the profiler
plugin adapters on the CPU harness and produces:

- one complete seven-stage recovery-episode trace (store -> preempt -> H2D
  restore -> admission -> first compute);
- one no-pressure trace (stores only, no recovery episode);
- run_metadata.json (exact commits, environment, command, timestamps);
- g1_verification.json (G1 acceptance items -> result/coverage).

Run with the vLLM-HUST G1 runtime on PYTHONPATH:

    PYTHONPATH=/root/vllm-hust-g1-default-off-f229ba7:/root/vllm-request-lifecycle-profiler-plugin-config-cleanup/src \
    /root/vllm-hust/.venv/bin/python .benchmarks/seal_g1_cpu_controlled_trace.py
"""

from __future__ import annotations

import itertools
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = Path("/root/vllm-hust-g1-default-off-f229ba7")
RESULT_DIR = REPO_ROOT / ".benchmarks" / "results" / "g1_cpu_controlled_trace_20260808"

RUN_ID = "1" * 32
CLOCK_DOMAIN_ID = "3" * 32
PROCESS_UUID = "2" * 32


def git_head(path: Path) -> dict[str, str]:
    return {
        "commit": subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"], text=True
        ).strip(),
        "branch": subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "--abbrev-ref", "HEAD"], text=True
        ).strip(),
        "dirty_files": subprocess.check_output(
            ["git", "-C", str(path), "status", "--porcelain"], text=True
        ).count("\n"),
    }


def build_hooks(out_dir: Path, clock_iter: itertools.count | None = None):
    from vllm_request_lifecycle_profiler.kv_recovery_profile_protocol import (
        KVRecoveryProfileConfig,
    )
    from vllm_request_lifecycle_profiler.runtime_hooks import (
        JsonlTraceSink,
        RuntimeLifecycleHooks,
        RuntimeTraceConfig,
    )
    from vllm_request_lifecycle_profiler.runtime_protocol import (
        KV_RECOVERY_COMMUNICATION_MODE,
        RuntimeProvenance,
    )

    _clock_iter = clock_iter if clock_iter is not None else itertools.count(1000, 5)
    sink = JsonlTraceSink(
        out_dir / "trace",
        RuntimeProvenance("a" * 40, "b" * 40, "c" * 40),
        communication_mode=KV_RECOVERY_COMMUNICATION_MODE,
        kv_recovery_profile_config=KVRecoveryProfileConfig(run_id=RUN_ID),
        clock_ns=lambda: next(_clock_iter),
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: PROCESS_UUID,
    )
    hooks = RuntimeLifecycleHooks(
        RuntimeTraceConfig(
            export_path=out_dir / "trace",
            provenance=RuntimeProvenance("a" * 40, "b" * 40, "c" * 40),
            communication_mode=KV_RECOVERY_COMMUNICATION_MODE,
            kv_recovery_profile_config=KVRecoveryProfileConfig(run_id=RUN_ID),
        ),
        sink=sink,
    )
    return hooks


def make_factory(hooks):
    from vllm_request_lifecycle_profiler.kv_recovery_runtime import (
        KVRecoveryObserverFactoryAdapter,
        KVRecoveryRuntimeABI,
        RuntimeBaseLifecycleBridge,
    )

    abi = KVRecoveryRuntimeABI.load()
    bridge = RuntimeBaseLifecycleBridge(hooks)
    factory = KVRecoveryObserverFactoryAdapter(RUN_ID, hooks, bridge, abi)
    return factory, abi


def make_runner(monkeypatch_hook=None):
    import vllm.distributed.kv_transfer.kv_connector.v1.offloading_connector as oc
    import vllm.v1.kv_recovery_profile as rp
    from tests.v1.kv_connector.unit.offloading_connector.utils import request_runner

    rp._observer_factory = monkeypatch_hook
    rp._observer_factory_ready_pid = rp._observer_factory_pid
    oc.kv_recovery_runtime_scope_enabled = lambda *a, **k: True

    block_size = 4
    block_size_factor = 3
    offloaded_block_size = block_size * block_size_factor
    gen = request_runner.__wrapped__()
    runner = next(gen)(
        block_size=block_size,
        num_gpu_blocks=100,
        async_scheduling=True,
        block_size_factor=block_size_factor,
    )

    handler = runner.offloading_spec.handler
    original_complete_jobs = handler.complete_jobs

    def complete_jobs_with_measurements(job_ids):
        original_complete_jobs(job_ids)
        for result in handler.completed_transfers:
            if result.transfer_size is None:
                result.transfer_size = 128
                result.transfer_time = 0.25

    handler.complete_jobs = complete_jobs_with_measurements

    original_start_kv = runner.worker_connector.connector_worker.start_kv_transfers

    def start_kv_with_first_compute(metadata):
        original_start_kv(metadata)
        runner.worker_connector.observe_kv_recovery_first_compute(
            {req.request_id for req in runner.scheduler.running}
        )

    runner.worker_connector.connector_worker.start_kv_transfers = (
        start_kv_with_first_compute
    )
    return runner, block_size, block_size_factor, offloaded_block_size


def scenario_recovery(out_dir: Path) -> dict[str, object]:
    """Store -> preempt -> H2D restore -> admission -> first compute."""
    from tests.v1.kv_connector.unit.offloading_connector.test_kv_recovery_scheduler import (
        generate_store_output,
    )

    hooks = build_hooks(out_dir)
    factory, _abi = make_factory(hooks)
    runner, _bs, _bsf, offloaded_block_size = make_runner(factory)

    free_blocks = runner.scheduler.kv_cache_manager.block_pool.free_block_queue
    initial_free_blocks = free_blocks.num_free_blocks
    runner.new_request(token_ids=[0] * offloaded_block_size * 2)
    runner.manager.prepare_store.side_effect = lambda keys, req_context: (
        generate_store_output(keys)
    )
    runner.run(decoded_tokens=[0], complete_transfers=False)
    runner.manager.prepare_store.side_effect = lambda keys, req_context: (
        generate_store_output(keys)
    )
    runner.run(
        decoded_tokens=[0] * (2 * offloaded_block_size - _bs),
        complete_transfers=False,
    )
    free_blocks.num_free_blocks = 0
    runner.run(
        decoded_tokens=[],
        complete_transfers=False,
        expected_flushed=tuple(range(9)),
        expected_stored=tuple(range(9)),
    )
    free_blocks.num_free_blocks = initial_free_blocks
    runner.scheduler.reset_prefix_cache()
    runner.connector_scheduler._maximal_prefix_lookup = lambda key, context: 3
    runner.manager.prepare_store.side_effect = lambda keys, req_context: (
        generate_store_output(keys)
    )
    runner.run(decoded_tokens=[0] * _bs, expected_loaded=tuple(range(9)))

    close_result = hooks.close()
    return close_result


def scenario_no_pressure(out_dir: Path) -> dict[str, object]:
    """Stores only; no preemption -> no recovery episode."""
    from tests.v1.kv_connector.unit.offloading_connector.test_kv_recovery_scheduler import (
        generate_store_output,
    )

    hooks = build_hooks(out_dir)
    factory, _abi = make_factory(hooks)
    runner, _bs, _bsf, offloaded_block_size = make_runner(factory)

    runner.new_request(token_ids=[0] * offloaded_block_size * 2)
    runner.manager.prepare_store.side_effect = lambda keys, req_context: (
        generate_store_output(keys)
    )
    runner.run(decoded_tokens=[0], complete_transfers=False)
    runner.manager.prepare_store.side_effect = lambda keys, req_context: (
        generate_store_output(keys)
    )
    runner.run(
        decoded_tokens=[0] * (2 * offloaded_block_size - _bs),
        complete_transfers=False,
    )

    close_result = hooks.close()
    return close_result


def scenario_recovery_requeue(out_dir: Path) -> dict[str, object]:
    """Adapter-driven full episode with two requeues and a monotonic clock,
    producing the complete eight-milestone chain (seven stages + 2 requeues)."""
    import vllm.v1.kv_recovery_profile as rp

    from vllm_request_lifecycle_profiler.kv_recovery_runtime import (
        KVRecoveryObserverFactoryAdapter,
        KVRecoveryRuntimeABI,
        RuntimeBaseLifecycleBridge,
    )

    clock_iter = itertools.count(1000, 7)
    hooks = build_hooks(out_dir, clock_iter=clock_iter)
    abi = KVRecoveryRuntimeABI.load()
    bridge = RuntimeBaseLifecycleBridge(hooks)
    factory = KVRecoveryObserverFactoryAdapter(
        RUN_ID, hooks, bridge, abi, clock_ns=lambda: next(clock_iter)
    )
    scheduler = factory.create_scheduler_observer()
    worker = factory.create_worker_observer()
    assert scheduler is not None and worker is not None

    req = "request-requeue"
    scheduler.request_started(req)
    scheduler.request_scheduled(req, "prefill", 1, 2, 0)
    scheduler.request_preempted(req, 1)
    context = scheduler.prepare_transfer_context(
        req,
        "h2d_restore",
        (
            rp.KVRecoveryBlockCoordinate(0, 0),
            rp.KVRecoveryBlockCoordinate(0, 1),
        ),
    )
    assert context is not None
    attempt = worker.begin_transfer(7, context)
    assert attempt is not None
    worker.transfer_submitted(attempt, next(clock_iter))
    receipt = worker.transfer_completed(7, next(clock_iter), True, 256, 5)
    assert receipt is not None
    scheduler.consume_h2d_receipts((receipt,), False)
    scheduler.request_admission_started(req, 1)
    scheduler.request_requeued(req, 1, "token_budget")
    scheduler.request_requeued(req, 1, "block_capacity")
    compute_context = scheduler.request_admitted(req, 1, "prefill", 2, 0)
    assert compute_context is not None
    worker.first_compute(compute_context, next(clock_iter))
    worker.close()
    scheduler.close()
    return hooks.close()


def collect(out_dir: Path) -> dict[str, object]:
    profile_paths = sorted(out_dir.glob("trace.rlp-kv-recovery.*.jsonl"))
    base_paths = sorted(out_dir.glob("trace.rlp.*.jsonl"))
    profile_records = []
    for p in profile_paths:
        for line in p.read_text().splitlines():
            profile_records.append(json.loads(line))
    milestones = [
        r for r in profile_records if r.get("record_type") == "recovery_event"
    ]
    milestone_timestamps = [
        (r.get("stage"), r.get("occurrence"), r.get("timestamp_ns")) for r in milestones
    ]
    h2d = [
        r
        for r in profile_records
        if r.get("record_type") == "transfer_event"
        and r.get("operation") == "h2d_restore"
    ]
    losses = [r for r in profile_records if r.get("record_type") == "loss_interval"]
    summaries = [
        r for r in profile_records if r.get("record_type") == "profile_summary"
    ]
    summary = summaries[-1] if summaries else None
    return {
        "profile_shards": [p.name for p in profile_paths],
        "base_shards": [p.name for p in base_paths],
        "recovery_stages": [r.get("stage") for r in milestones],
        "recovery_milestone_timestamps": milestone_timestamps,
        "h2d_transfer_phases": [
            (r.get("transfer_phase"), r.get("recovery_epoch")) for r in h2d
        ],
        "loss_intervals": len(losses),
        "summary": summary,
    }


def main() -> int:
    if RESULT_DIR.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archived = RESULT_DIR.with_name(RESULT_DIR.name + f".archived_{stamp}")
        RESULT_DIR.rename(archived)
        print(f"archived previous run to {archived.name}")
    RESULT_DIR.mkdir(parents=True)
    rec_dir = RESULT_DIR / "recovery_episode"
    nop_dir = RESULT_DIR / "no_pressure"
    rec_dir.mkdir()
    nop_dir.mkdir()

    rec_close = scenario_recovery(rec_dir)
    rq_dir = RESULT_DIR / "recovery_episode_requeue"
    rq_dir.mkdir()
    rq_close = scenario_recovery_requeue(rq_dir)
    nop_close = scenario_no_pressure(nop_dir)

    rec = collect(rec_dir)
    rq = collect(rq_dir)
    nop = collect(nop_dir)

    # The runtime emits zero or more requeue records between scheduler_wakeup
    # and admission (the harness admits directly, so zero is expected here).
    # Requeue variants (0/1/multiple + bounded reason) are covered by the
    # integration matrix; the canonical order must hold once requeue is
    # filtered out.
    def core_order(stages):
        return [s for s in stages if s != "requeue"]

    expected_core = [
        "preempt",
        "restore_start",
        "restore_done",
        "scheduler_wakeup",
        "admission",
        "first_prefill_or_decode",
    ]
    expected_requeue_chain = [
        "preempt",
        "restore_start",
        "restore_done",
        "scheduler_wakeup",
        "requeue",
        "requeue",
        "admission",
        "first_prefill_or_decode",
    ]

    def ns_decomposition_ok(timestamps) -> bool:
        times = [t for _s, _o, t in timestamps]
        if any(t is None for t in times):
            return False
        return all(a < b for a, b in itertools.pairwise(times))

    # Derive requeue occurrences/reasons from the requeue scenario stages.
    rq_reasons: list[object] = []
    rq_occurrences: list[object] = []
    for shard in rq["profile_shards"]:
        for line in (rq_dir / shard).read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if (
                row.get("record_type") == "recovery_event"
                and row.get("stage") == "requeue"
            ):
                rq_reasons.append(row.get("requeue_reason"))
                rq_occurrences.append(row.get("occurrence"))

    verification = {
        "recovery_episode": {
            "seven_stage_order_ok": core_order(rec["recovery_stages"]) == expected_core,
            "actual_stages": rec["recovery_stages"],
            "requeue_count": rec["recovery_stages"].count("requeue"),
            "h2d_transfer_submit_done": [p for p, _ in rec["h2d_transfer_phases"]]
            == ["submit", "done"],
            "h2d_epochs": sorted({e for _, e in rec["h2d_transfer_phases"]}),
            "loss_intervals": rec["loss_intervals"],
            "close_outcome": rec_close.close_outcome if rec_close else None,
            "summary": rec["summary"],
        },
        "recovery_episode_requeue": {
            "full_chain_ok": rq["recovery_stages"] == expected_requeue_chain,
            "actual_stages": rq["recovery_stages"],
            "requeue_occurrences": rq_occurrences,
            "requeue_reasons": rq_reasons,
            "monotonic_ns_ok": ns_decomposition_ok(rq["recovery_milestone_timestamps"]),
            "loss_intervals": rq["loss_intervals"],
            "close_outcome": rq_close.close_outcome if rq_close else None,
            "summary": rq["summary"],
        },
        "no_pressure": {
            "recovery_stage_count": len(nop["recovery_stages"]),
            "loss_intervals": nop["loss_intervals"],
            "close_outcome": nop_close.close_outcome if nop_close else None,
            "summary": nop["summary"],
        },
    }

    run_metadata = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": " ".join(sys.argv),
        "python": sys.version.split()[0],
        "profiler_repo": {
            "path": str(REPO_ROOT),
            **git_head(REPO_ROOT),
        },
        "runtime_repo": {
            "path": str(RUNTIME_ROOT),
            **git_head(RUNTIME_ROOT),
        },
        "env": {
            k: v
            for k, v in {
                "VLLM_HUST_G1_SRC": os.environ.get("VLLM_HUST_G1_SRC"),
                "PYTHONPATH": os.environ.get("PYTHONPATH"),
            }.items()
            if v
        },
        "scenarios": [
            "recovery_episode",
            "recovery_episode_requeue",
            "no_pressure",
        ],
    }

    (RESULT_DIR / "run_metadata.json").write_text(
        json.dumps(run_metadata, indent=2) + "\n", encoding="utf-8"
    )
    (RESULT_DIR / "g1_verification.json").write_text(
        json.dumps(verification, indent=2) + "\n", encoding="utf-8"
    )

    print("G1 seal results:")
    print(json.dumps(verification, indent=2))
    ok = (
        verification["recovery_episode"]["seven_stage_order_ok"]
        and verification["recovery_episode"]["requeue_count"] == 0
        and verification["recovery_episode"]["h2d_transfer_submit_done"]
        and verification["recovery_episode"]["loss_intervals"] == 0
        and verification["recovery_episode"]["close_outcome"] == "drained"
        and verification["recovery_episode_requeue"]["full_chain_ok"]
        and verification["recovery_episode_requeue"]["requeue_occurrences"] == [0, 1]
        and verification["recovery_episode_requeue"]["requeue_reasons"]
        == ["token_budget", "block_capacity"]
        and verification["recovery_episode_requeue"]["monotonic_ns_ok"]
        and verification["recovery_episode_requeue"]["loss_intervals"] == 0
        and verification["recovery_episode_requeue"]["close_outcome"] == "drained"
        and verification["no_pressure"]["recovery_stage_count"] == 0
        and verification["no_pressure"]["loss_intervals"] == 0
        and verification["no_pressure"]["close_outcome"] == "drained"
    )
    print("G1_SEAL:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
