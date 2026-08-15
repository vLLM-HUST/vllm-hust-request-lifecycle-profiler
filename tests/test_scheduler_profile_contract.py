from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_scheduler_profile_contract.py"
SPEC = importlib.util.spec_from_file_location("scheduler_profile_contract", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
CONTRACT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTRACT)


def _golden_records() -> list[dict[str, object]]:
    return CONTRACT.load_json(CONTRACT.FIXTURES / "scheduler-wire-golden.json")[
        "records"
    ]


def _record(record_type: str) -> dict[str, object]:
    return copy.deepcopy(
        next(
            record
            for record in _golden_records()
            if record["record_type"] == record_type
        )
    )


def _write_wire_fixture(tmp_path: Path, records: list[dict[str, object]]) -> Path:
    fixture_records = copy.deepcopy(records)
    fixture_records[-1]["content_sha256"] = hashlib.sha256(
        b"".join(
            CONTRACT.canonicalize(record) + b"\n" for record in fixture_records[:-1]
        )
    ).hexdigest()
    path = tmp_path / "scheduler-wire.json"
    path.write_text(
        json.dumps(
            {"schema_version": 1, "records": fixture_records},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _complete_scheduler_shard(
    tmp_path: Path, records: list[dict[str, object]] | None = None
) -> Path:
    values = copy.deepcopy(records if records is not None else _golden_records())
    values = [record for record in values if record["record_type"] != "loss_interval"]
    sequence = 0
    for record in values:
        if "record_seq" in record:
            record["record_seq"] = sequence
            sequence += 1
    summary = values[-1]
    summary.update(
        {
            "attempted_data_count": sequence,
            "written_loss_interval_count": 0,
            "dropped_data_count": 0,
            "first_data_record_seq": 0,
            "last_data_record_seq": sequence - 1,
            "writer_failure_count": 0,
            "close_outcome": "drained",
        }
    )
    summary["content_sha256"] = hashlib.sha256(
        b"".join(CONTRACT.canonicalize(record) + b"\n" for record in values[:-1])
    ).hexdigest()
    path = tmp_path / "scheduler.jsonl"
    path.write_bytes(
        b"".join(CONTRACT.canonicalize(record) + b"\n" for record in values)
    )
    return path


def test_complete_contract_verifies() -> None:
    report = CONTRACT.verify()
    assert report["valid"] is True
    assert report["wire_golden"]["records"] == 12
    assert report["wire_golden"]["data_records"] == 9
    written_sequences = [
        record["record_seq"] for record in _golden_records() if "record_seq" in record
    ]
    assert written_sequences == [0, 1, 2, 3, 5, 6, 7, 8, 9]
    assert (
        report["wire_golden"]["generated_maximal_cycle_bytes"]
        <= report["wire_golden"]["record_limit_bytes"]
    )


def test_wire_rejects_unknown_member_and_boolean_integer() -> None:
    cycle = _record("schedule_cycle")
    cycle["unknown"] = 1
    with pytest.raises(CONTRACT.ContractError, match="invalid_members:schedule_cycle"):
        CONTRACT.validate_record(cycle, 8192)

    cycle = _record("schedule_cycle")
    cycle["record_seq"] = True
    with pytest.raises(CONTRACT.ContractError, match="invalid_uint64:record_seq"):
        CONTRACT.validate_record(cycle, 8192)


def test_zero_token_batch_is_retained_but_never_relation_candidate_eligible() -> None:
    batch = _record("logical_batch")
    batch.update(
        {
            "logical_batch_kind": "empty_control",
            "scheduled_token_count": 0,
            "prefill_token_count": 0,
            "decode_token_count": 0,
            "runtime_device_relation_candidate_eligible": True,
        }
    )
    with pytest.raises(CONTRACT.ContractError, match="invalid_empty_control_batch"):
        CONTRACT.validate_record(batch, 8192)


def test_batch_kind_closes_scheduled_request_count_domain() -> None:
    work = _record("logical_batch")
    work["scheduled_engine_request_count"] = 0
    with pytest.raises(CONTRACT.ContractError, match="invalid_work_batch"):
        CONTRACT.validate_record(work, 8192)

    empty = next(
        copy.deepcopy(record)
        for record in _golden_records()
        if record.get("logical_batch_kind") == "empty_control"
    )
    empty["scheduled_engine_request_count"] = 1
    with pytest.raises(CONTRACT.ContractError, match="invalid_empty_control_batch"):
        CONTRACT.validate_record(empty, 8192)


def test_constraint_bucket_balance_and_order_are_closed() -> None:
    cycle = _record("schedule_cycle")
    cycle["token_budget_summary"]["buckets"][3]["count"] = 2
    with pytest.raises(CONTRACT.ContractError, match="constraint_balance"):
        CONTRACT.validate_record(cycle, 8192)

    cycle = _record("schedule_cycle")
    buckets = cycle["active_sequence_cap_summary"]["buckets"]
    buckets[0], buckets[1] = buckets[1], buckets[0]
    with pytest.raises(CONTRACT.ContractError, match="invalid_bucket_order"):
        CONTRACT.validate_record(cycle, 8192)


def test_config_rejects_boolean_capacity_and_weakened_composition_boundary() -> None:
    config = CONTRACT.load_json(CONTRACT.CONFIG_PATH)
    mutated = copy.deepcopy(config)
    mutated["wire_limits"]["data_capacity_records"] = True
    with pytest.raises(CONTRACT.ContractError, match="invalid_wire_limit"):
        CONTRACT.verify_config(mutated)

    mutated = copy.deepcopy(config)
    mutated["composition_boundary"]["timestamp_containment_maximum_status"] = "exact"
    with pytest.raises(CONTRACT.ContractError, match="invalid_composition_boundary"):
        CONTRACT.verify_config(mutated)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("communication_mode", "kv_transfer"),
        ("kv_transfer_connector_enabled", True),
        ("ec_transfer_connector_enabled", True),
    ],
)
def test_runtime_profile_freezes_connector_disabled_state(
    field: str, invalid_value: object
) -> None:
    config = CONTRACT.load_json(CONTRACT.CONFIG_PATH)
    mutated = copy.deepcopy(config)
    mutated["runtime_profile"][field] = invalid_value
    with pytest.raises(CONTRACT.ContractError, match="invalid_runtime_profile"):
        CONTRACT.verify_config(mutated)


def test_clock_bridge_sample_must_share_start_clock_domain(tmp_path: Path) -> None:
    records = _golden_records()
    sample = next(
        record for record in records if record["record_type"] == "clock_bridge_sample"
    )
    sample["clock_domain_id"] = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    path = _write_wire_fixture(tmp_path, records)
    config = CONTRACT.load_json(CONTRACT.CONFIG_PATH)
    with pytest.raises(CONTRACT.ContractError, match="clock_domain_mismatch"):
        CONTRACT.validate_wire_golden(path, config)


def test_loss_interval_exactly_covers_an_interior_record_gap(tmp_path: Path) -> None:
    records = _golden_records()
    config = CONTRACT.load_json(CONTRACT.CONFIG_PATH)
    valid_path = _write_wire_fixture(tmp_path, records)
    CONTRACT.validate_wire_golden(valid_path, config)

    loss = next(
        record for record in records if record["record_type"] == "loss_interval"
    )
    loss["first_dropped_record_seq"] = 9
    loss["last_dropped_record_seq"] = 9
    invalid_path = _write_wire_fixture(tmp_path, records)
    with pytest.raises(CONTRACT.ContractError, match="wire_record_sequence_coverage"):
        CONTRACT.validate_wire_golden(invalid_path, config)


def test_cycle_must_finish_before_linked_execution_dispatch(tmp_path: Path) -> None:
    records = _golden_records()
    cycle = next(
        record for record in records if record["record_type"] == "schedule_cycle"
    )
    batch = next(
        record
        for record in records
        if record["record_type"] == "logical_batch"
        and record["logical_batch_id"] == cycle["logical_batch_id"]
    )
    start = next(
        record
        for record in records
        if record["record_type"] == "execution_step_start"
        and record["execution_step_id"] == batch["execution_step_id"]
    )
    start["dispatch_monotonic_ns"] = cycle["cycle_end_monotonic_ns"] - 1
    path = _write_wire_fixture(tmp_path, records)
    config = CONTRACT.load_json(CONTRACT.CONFIG_PATH)
    with pytest.raises(CONTRACT.ContractError, match="invalid_cycle_execution_order"):
        CONTRACT.validate_wire_golden(path, config)


@pytest.mark.parametrize("duplicate_type", ["scheduler_start", "scheduler_summary"])
def test_wire_rejects_duplicate_control_records(
    tmp_path: Path, duplicate_type: str
) -> None:
    records = _golden_records()
    duplicate = copy.deepcopy(
        next(record for record in records if record["record_type"] == duplicate_type)
    )
    records.insert(-1, duplicate)
    path = _write_wire_fixture(tmp_path, records)
    config = CONTRACT.load_json(CONTRACT.CONFIG_PATH)
    with pytest.raises(CONTRACT.ContractError, match="wire_control_cardinality"):
        CONTRACT.validate_wire_golden(path, config)


def test_composition_authority_is_external_and_status_domain_is_closed() -> None:
    config = CONTRACT.load_json(CONTRACT.CONFIG_PATH)
    boundary = config["composition_boundary"]
    assert boundary["authority"] == "experiment_repo_run_manifest/v1"
    assert boundary["relation_statuses"] == [
        "exact",
        "correlated",
        "ambiguous",
        "unmatched",
        "unsupported",
    ]
    assert "scheduler_selected_profile_database" in boundary[
        "forbidden_identity_authorities"
    ]


def test_data_records_cannot_claim_pid_rank_device_or_database() -> None:
    forbidden = {
        "pid",
        "context_id",
        "rank_id",
        "device_id",
        "analysis_db_path",
        "traceloom_run_id",
    }
    for record in _golden_records():
        if record["record_type"] not in {"scheduler_start", "scheduler_summary"}:
            assert forbidden.isdisjoint(record)


def test_start_and_summary_scope_must_match(tmp_path: Path) -> None:
    records = _golden_records()
    records[-1]["process_instance_id"] = "P1"
    path = _write_wire_fixture(tmp_path, records)
    config = CONTRACT.load_json(CONTRACT.CONFIG_PATH)
    with pytest.raises(CONTRACT.ContractError, match="wire_scope_mismatch"):
        CONTRACT.validate_wire_golden(path, config)


def test_golden_contains_every_record_and_all_constraint_modes() -> None:
    records = _golden_records()
    assert {record["record_type"] for record in records} == set(
        CONTRACT.FIELDS_BY_RECORD_TYPE
    )
    cycles = [record for record in records if record["record_type"] == "schedule_cycle"]
    token_modes = {
        bucket["mode"]
        for cycle in cycles
        for bucket in cycle["token_budget_summary"]["buckets"]
        if bucket["count"]
    }
    cap_modes = {
        bucket["mode"]
        for cycle in cycles
        for bucket in cycle["active_sequence_cap_summary"]["buckets"]
        if bucket["count"]
    }
    assert token_modes == {"not_limited", "clipped", "stopped_no_chunk"}
    assert cap_modes == {"not_limited", "stopped_at_cap"}
    assert any(
        record.get("logical_batch_kind") == "empty_control" for record in records
    )


def test_emitted_scheduler_shard_produces_route_b_validation_receipt(
    tmp_path: Path,
) -> None:
    shard = _complete_scheduler_shard(tmp_path)

    receipt = CONTRACT.build_scheduler_validation_receipt(
        shard, verifier_commit="a" * 40
    )

    assert receipt["artifact_kind"] == "scheduler_validation_receipt"
    assert receipt["scheduler_shard_sha256"] == CONTRACT.sha256_file(shard)
    assert receipt["scope"]["scheduler_shard_id"] == "SH0"
    assert receipt["validation"] == {
        "valid": True,
        "record_count": 11,
        "data_record_count": 9,
        "dropped_data_count": 0,
        "writer_failure_count": 0,
        "close_outcome": "drained",
        "wire_content_sha256": json.loads(
            shard.read_text(encoding="utf-8").splitlines()[-1]
        )["content_sha256"],
    }


def test_scheduler_shard_cli_writes_commit_bound_receipt(tmp_path: Path) -> None:
    shard = _complete_scheduler_shard(tmp_path)
    receipt_path = tmp_path / "scheduler-validation.json"

    output = subprocess.check_output(
        [
            sys.executable,
            str(ROOT / "scripts" / "verify_scheduler_profile_contract.py"),
            "--scheduler-shard",
            str(shard),
            "--write-receipt",
            str(receipt_path),
            "--json",
        ],
        text=True,
    )

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert json.loads(output) == receipt
    assert receipt["verifier_commit"] == subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
    ).strip()


def test_emitted_scheduler_shard_rejects_constraint_tampering(
    tmp_path: Path,
) -> None:
    records = _golden_records()
    cycle = next(
        record for record in records if record["record_type"] == "schedule_cycle"
    )
    cycle["token_budget_summary"]["accounted_count"] += 1
    shard = _complete_scheduler_shard(tmp_path, records)
    config = CONTRACT.load_json(CONTRACT.CONFIG_PATH)

    with pytest.raises(CONTRACT.ContractError, match="constraint_balance"):
        CONTRACT.validate_scheduler_shard(shard, config)


def test_emitted_scheduler_shard_requires_complete_drained_writer(
    tmp_path: Path,
) -> None:
    shard = _complete_scheduler_shard(tmp_path)
    records = [
        json.loads(line) for line in shard.read_text(encoding="utf-8").splitlines()
    ]
    records[-1]["writer_failure_count"] = 1
    records[-1]["close_outcome"] = "writer_failure"
    records[-1]["content_sha256"] = hashlib.sha256(
        b"".join(CONTRACT.canonicalize(record) + b"\n" for record in records[:-1])
    ).hexdigest()
    shard.write_bytes(
        b"".join(CONTRACT.canonicalize(record) + b"\n" for record in records)
    )
    config = CONTRACT.load_json(CONTRACT.CONFIG_PATH)

    with pytest.raises(
        CONTRACT.ContractError, match="scheduler_shard_incomplete_for_route_b"
    ):
        CONTRACT.validate_scheduler_shard(shard, config)


def test_pr_c1_adds_no_runtime_scheduler_profiler_implementation() -> None:
    production_hits = []
    for path in (ROOT / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "rlp.scheduler/v1alpha1" in text or "scheduler_profile" in text:
            production_hits.append(path.relative_to(ROOT).as_posix())
    assert production_hits == []
