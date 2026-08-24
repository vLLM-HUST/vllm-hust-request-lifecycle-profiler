from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path

import pytest


def _runner():
    path = Path(__file__).parents[1] / ".benchmarks/run_issue19_m0_baseline.py"
    spec = importlib.util.spec_from_file_location("issue19_m0_runner", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _row(pid: int, ppid: int, comm: str, args: str = "") -> dict[str, object]:
    return {"pid": pid, "ppid": ppid, "comm": comm, "args": args or comm}


def test_tp1_runner_forces_multiproc_backend() -> None:
    command = _runner()._server_command(18179)

    option = command.index("--distributed-executor-backend")
    assert command[option + 1] == "mp"


def test_normal_control_disables_fault_roles_but_preserves_survivor_set() -> None:
    runner = _runner()

    assert runner._role_for_ordinal(1, normal_control=True) == "normal_control"
    assert runner._role_for_ordinal(5, normal_control=True) == "normal_control"
    assert runner._role_for_ordinal(6, normal_control=True) == "unaffected_survivor"
    assert len(runner.UNAFFECTED_ORDINALS) == 58


def test_server_environment_resolves_child_paths_to_absolute() -> None:
    environment = _runner()._server_environment(
        Path("relative-results/r00"), 7, "a" * 32
    )

    assert Path(environment["VLLM_RLP_TRACE_EXPORT_PATH"]).is_absolute()
    assert Path(environment["VLLM_RLP_WORKER_FAILURE_SENTINEL_DIR"]).is_absolute()


def test_repetition_run_directory_is_absolute() -> None:
    runner = _runner()
    run_dir = runner._run_directory(
        Path("relative-results"), 0, 2026082000, "fault"
    )

    assert run_dir.is_absolute()
    assert run_dir.name == "r00-2026082000-fault"


def test_worker_selector_requires_worker_below_owned_engine() -> None:
    runner = _runner()
    rows = [
        _row(100, 1, "VLLM::APIServer"),
        _row(110, 100, "VLLM::EngineCor", "VLLM::EngineCore"),
        _row(120, 110, "VLLM::Worker", "VLLM::Worker"),
        _row(999, 1, "VLLM::Worker", "VLLM::Worker"),
    ]

    selected = runner._owned_worker_process(100, rows)

    assert selected["pid"] == 120
    assert selected["engine_pid"] == 110


def test_worker_selector_never_substitutes_uniproc_engine() -> None:
    runner = _runner()
    rows = [
        _row(100, 1, "VLLM::APIServer"),
        _row(110, 100, "VLLM::EngineCor", "VLLM::EngineCore"),
    ]

    with pytest.raises(RuntimeError, match="refusing EngineCore substitution"):
        runner._owned_worker_process(100, rows)


def test_terminal_chain_normalizes_client_terminal_then_engine_abort() -> None:
    runner = _runner()
    events = [
        {
            "_source": "api.jsonl",
            "event_name": "cancelled",
            "timestamp_ns": 10,
            "metadata": {"terminal_cause": "client_disconnect"},
        },
        {
            "_source": "engine.jsonl",
            "event_name": "aborted",
            "timestamp_ns": 20,
            "metadata": {"terminal_cause": "explicit_cancel"},
        },
    ]

    assert runner._terminal_chain_valid(events)
    assert not runner._terminal_chain_valid([events[0], {**events[0]}])


def test_terminal_chain_normalizes_engine_failure_across_core_and_api() -> None:
    runner = _runner()
    events = [
        {
            "_source": "engine.jsonl",
            "event_name": "error",
            "timestamp_ns": 10,
            "metadata": {"terminal_cause": "engine_failure"},
        },
        {
            "_source": "api.jsonl",
            "event_name": "error",
            "timestamp_ns": 20,
            "metadata": {"terminal_cause": "engine_failure"},
        },
    ]

    assert runner._terminal_chain_valid(events)


def test_unclosed_observer_shards_are_not_hidden_by_survivor_summaries() -> None:
    runner = _runner()
    records = [
        {
            "_source": "trace.worker.jsonl",
            "record_type": "process_start",
            "process_uuid": "a" * 32,
        },
        {
            "_source": "trace.engine.jsonl",
            "record_type": "process_start",
            "process_uuid": "b" * 32,
        },
        {
            "_source": "trace.engine.jsonl",
            "record_type": "process_summary",
            "process_uuid": "b" * 32,
        },
        {
            "_source": "trace.profile.worker.jsonl",
            "record_type": "profile_start",
            "process_uuid": "a" * 32,
        },
    ]

    assert runner._unclosed_observer_shards(records) == [
        {
            "stream": "trace",
            "source": "trace.worker.jsonl",
            "process_uuid": "a" * 32,
        },
        {
            "stream": "profile",
            "source": "trace.profile.worker.jsonl",
            "process_uuid": "a" * 32,
        },
    ]


def test_only_exact_killed_worker_shard_pair_can_be_externally_closed() -> None:
    runner = _runner()
    process_uuid = "a" * 32
    records = [
        {
            "record_type": "process_start",
            "process_uuid": process_uuid,
            "pid": 120,
        },
        {
            "record_type": "profile_start",
            "process_uuid": process_uuid,
            "pid": 120,
        },
    ]
    unclosed = [
        {
            "stream": "trace",
            "source": "trace.worker.jsonl",
            "process_uuid": process_uuid,
        },
        {
            "stream": "profile",
            "source": "profile.worker.jsonl",
            "process_uuid": process_uuid,
        },
    ]

    assert runner._externally_closed_worker_shards(records, unclosed, 120) == unclosed
    assert runner._externally_closed_worker_shards(records, unclosed, 121) == []
    assert runner._externally_closed_worker_shards(records, unclosed[:1], 120) == []


def test_stream_error_is_not_hidden_by_done_sentinel() -> None:
    runner = _runner()
    response = io.BytesIO(
        b'data: {"error":{"message":"EngineCore died","type":"InternalServerError"}}\n'
        b"data: [DONE]\n"
    )

    result = runner._read_stream(
        object(),
        response,
        submitted_at_ns=1,  # type: ignore[arg-type]
    )

    assert result[3] is True
    assert result[5] == (
        '{"message": "EngineCore died", "type": "InternalServerError"}'
    )


def test_complete_recovery_orders_cross_shard_events_by_timestamp() -> None:
    runner = _runner()
    runtime_id = "chatcmpl-request-0"
    episode_id = "a" * 32 + ":e:0:k:1"
    rows = [
        {
            "record_type": "recovery_event",
            "runtime_request_id": runtime_id,
            "episode_id": episode_id,
            "stage": stage,
            "timestamp_ns": index,
        }
        for index, stage in enumerate(runner.RECOVERY_STAGES, start=1)
    ]
    cross_shard_file_order = [rows[3], rows[4], rows[0], rows[1], rows[2], rows[5]]

    assert runner._complete_recovery(cross_shard_file_order, runtime_id)


def _resource_event(
    name: str,
    timestamp_ns: int,
    resource_type: str,
    resource_id: str,
    generation: str,
) -> dict[str, object]:
    transition = {
        "resource_acquired": "acquire",
        "resource_transfer_pending": "transfer_pending",
        "resource_released": "release",
        "resource_invalidated": "invalidate",
    }[name]
    return {
        "record_type": "event",
        "event_id": f"event-{timestamp_ns}",
        "event_name": name,
        "timestamp_ns": timestamp_ns,
        "metadata": {
            "runtime_request_id": "request-0",
            "resource_type": resource_type,
            "resource_id": resource_id,
            "resource_transition": transition,
            "resource_units": 1,
            "worker_generation": generation,
        },
    }


def test_resource_ledger_requires_persisted_capacity_and_transfer_ownership() -> None:
    runner = _runner()
    ledger = runner._resource_ledger([], [], None, [])

    assert ledger["complete"] is False
    assert ledger["errors"] == [
        {
            "reason": "missing_resource_types",
            "types": ["kv_capacity_lease", "offload_transfer"],
        }
    ]


def test_resource_ledger_closes_pending_transfer_only_on_exact_generation_exit() -> (
    None
):
    runner = _runner()
    generation = "VllmWorker-0:120"
    transfer_id = "a" * 32 + ":t:1"
    base = [
        _resource_event(
            "resource_acquired",
            1,
            "kv_capacity_lease",
            "kv-lease:one:0",
            "EngineCore:110",
        ),
        _resource_event(
            "resource_released",
            2,
            "kv_capacity_lease",
            "kv-lease:one:0",
            "EngineCore:110",
        ),
        _resource_event(
            "resource_acquired", 3, "offload_transfer", transfer_id, generation
        ),
        _resource_event(
            "resource_transfer_pending", 4, "offload_transfer", transfer_id, generation
        ),
    ]
    profile = [
        {
            "record_type": "transfer_event",
            "transfer_phase": "submit",
            "transfer_id": transfer_id,
        }
    ]
    monitor = [{"timestamp_ns": 5}]

    ledger = runner._resource_ledger(base, profile, generation, monitor)

    assert ledger["complete"] is True
    assert ledger["orphan_resources"] == []
    assert [
        row["resource_id"] for row in ledger["externally_invalidated_resources"]
    ] == [transfer_id]


def test_crash_safe_witness_supplies_exact_pending_transfer_ownership() -> None:
    runner = _runner()
    generation = "VllmWorker-0:120"
    transfer_id = "a" * 32 + ":t:1"
    capacity_rows = [
        _resource_event(
            "resource_acquired",
            1,
            "kv_capacity_lease",
            "kv-lease:one:0",
            "EngineCore:110",
        ),
        _resource_event(
            "resource_released",
            2,
            "kv_capacity_lease",
            "kv-lease:one:0",
            "EngineCore:110",
        ),
    ]
    witness = {
        "transfer_id": transfer_id,
        "runtime_request_id": "request-0",
        "worker_generation": generation,
        "timestamp_ns": 3,
    }

    ledger = runner._resource_ledger(
        capacity_rows,
        [],
        generation,
        [{"timestamp_ns": 4}],
        witness,
    )

    assert ledger["complete"] is True
    assert [
        row["resource_id"] for row in ledger["externally_invalidated_resources"]
    ] == [transfer_id]


def test_crash_witness_repairs_partially_persisted_pending_prefix() -> None:
    runner = _runner()
    generation = "VllmWorker-0:120"
    transfer_id = "a" * 32 + ":t:1"
    base = [
        _resource_event(
            "resource_acquired",
            1,
            "kv_capacity_lease",
            "kv-lease:one:0",
            "EngineCore:110",
        ),
        _resource_event(
            "resource_released",
            2,
            "kv_capacity_lease",
            "kv-lease:one:0",
            "EngineCore:110",
        ),
        _resource_event(
            "resource_transfer_pending",
            3,
            "offload_transfer",
            transfer_id,
            generation,
        ),
    ]
    profile = [
        {
            "record_type": "transfer_event",
            "transfer_phase": "submit",
            "transfer_id": transfer_id,
        }
    ]
    witness = {
        "transfer_id": transfer_id,
        "runtime_request_id": "request-0",
        "worker_generation": generation,
        "timestamp_ns": 4,
    }

    ledger = runner._resource_ledger(
        base,
        profile,
        generation,
        [{"timestamp_ns": 5}],
        witness,
    )

    transfer = next(
        row for row in ledger["resources"] if row["resource_id"] == transfer_id
    )
    assert transfer["transitions"] == ["acquire", "transfer_pending"]
    assert ledger["complete"] is True


def test_duplicate_resource_closure_is_invalid_evidence_not_an_orphan() -> None:
    runner = _runner()
    base = [
        _resource_event(
            "resource_acquired",
            1,
            "kv_capacity_lease",
            "kv-lease:one:0",
            "EngineCore:110",
        ),
        _resource_event(
            "resource_released",
            2,
            "kv_capacity_lease",
            "kv-lease:one:0",
            "EngineCore:110",
        ),
        _resource_event(
            "resource_released",
            3,
            "kv_capacity_lease",
            "kv-lease:one:0",
            "EngineCore:110",
        ),
    ]

    ledger = runner._resource_ledger(base, [], None, [])

    assert ledger["complete"] is False
    assert ledger["orphan_resources"] == []
    assert any(row["reason"] == "invalid_resource_sequence" for row in ledger["errors"])


def _aggregate_result(*, evidence: bool, pathology: bool, latency=False):
    return {
        "evidence_valid": evidence,
        "correctness": evidence and not pathology,
        "pathology_observed": pathology,
        "latency_pathology_evaluable": latency,
        "latency_pathology_observed": False if latency else None,
        "latency_top1_boundary": None,
        "distribution": {"unaffected_survivor_p99_seconds": 1.0},
    }


def test_paired_latency_uses_same_fixed_survivor_set_and_graph_top1() -> None:
    runner = _runner()
    common = {
        "evidence_valid": True,
        "distribution": {"unaffected_survivor_count": 58},
    }
    fault = {
        **common,
        "distribution": {
            **common["distribution"],
            "unaffected_survivor_p99_seconds": 11.0,
        },
        "lifecycle_boundary_p99_seconds": {
            "queue_to_schedule": {"count": 58, "p99": 3.0},
            "prefill_to_decode_done": {"count": 58, "p99": 5.0},
        },
    }
    control = {
        **common,
        "distribution": {
            **common["distribution"],
            "unaffected_survivor_p99_seconds": 10.0,
        },
        "lifecycle_boundary_p99_seconds": {
            "queue_to_schedule": {"count": 58, "p99": 1.0},
            "prefill_to_decode_done": {"count": 58, "p99": 4.5},
        },
    }

    result = runner._paired_latency(fault, control)

    assert result["evaluable"] is True
    assert result["observed"] is True
    assert result["top1_boundary"] == "queue_to_schedule"
    assert result["relative_delta"] == pytest.approx(0.1)


def test_aggregate_latency_go_requires_same_top1_boundary(tmp_path) -> None:
    runner = _runner()
    results = []
    for index in range(10):
        result = _aggregate_result(evidence=True, pathology=False, latency=True)
        result["latency_pathology_observed"] = True
        result["latency_top1_boundary"] = (
            "queue_to_schedule" if index < 8 else "prefill_to_decode_done"
        )
        results.append(result)

    summary = runner._aggregate(tmp_path, results)

    assert summary["decision"] == "GO"
    assert summary["dominant_latency_top1_boundary"] == "queue_to_schedule"
    assert summary["dominant_latency_top1_boundary_count"] == 8


def test_aggregate_can_reach_go_when_valid_baseline_pathology_repeats(tmp_path) -> None:
    runner = _runner()
    results = [
        _aggregate_result(evidence=True, pathology=index < 8, latency=True)
        for index in range(10)
    ]

    summary = runner._aggregate(tmp_path, results)

    assert summary["decision"] == "GO"
    assert summary["correctness_100_percent"] is False
    assert summary["evidence_valid_100_percent"] is True


def test_aggregate_fails_closed_when_latency_comparator_is_missing(tmp_path) -> None:
    runner = _runner()
    results = [_aggregate_result(evidence=True, pathology=False) for _ in range(10)]

    summary = runner._aggregate(tmp_path, results)

    assert summary["decision"] == "INVALID_EVIDENCE"


def test_aggregate_rejects_missing_ownership_evidence(tmp_path) -> None:
    runner = _runner()
    results = [_aggregate_result(evidence=False, pathology=False) for _ in range(10)]

    summary = runner._aggregate(tmp_path, results)

    assert summary["decision"] == "INVALID_EVIDENCE"
