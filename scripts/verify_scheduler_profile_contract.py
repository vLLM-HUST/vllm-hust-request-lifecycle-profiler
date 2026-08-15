#!/usr/bin/env python3
"""Verify PR-C1 contract bytes and golden vectors without runtime imports."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
P1 = ROOT / "contracts" / "p1"
FIXTURES = P1 / "fixtures" / "scheduler-profile-v1alpha1"
CONFIG_PATH = P1 / "scheduler-profile-config.v1alpha1.json"
CANDIDATE_PATH = P1 / "scheduler-profile-approval-candidate.json"
CONTRACT_PATH = P1 / "scheduler-profile.v1alpha1-draft.md"
OVERLAY_PATH = P1 / "scheduler-profile-multistream-overlay.v1alpha1-draft.md"
ARCHITECTURE_PATH = P1 / "scheduler-profiler-infra.v0-draft.md"
ARCHITECTURE_OVERLAY_PATH = P1 / "scheduler-profile-multistream-overlay.v0-draft.md"

SAFE_INTEGER_MAX = 9_007_199_254_740_991
HEX32 = re.compile(r"^[0-9a-f]{32}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SHARD_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
OPAQUE_ID = re.compile(r"^[!-~]{1,128}$")
EXPECTED_CANDIDATE_ARTIFACTS = {
    "scheduler_wire_contract": "contracts/p1/scheduler-profile.v1alpha1-draft.md",
    "scheduler_profile_config": "contracts/p1/scheduler-profile-config.v1alpha1.json",
    "multistream_overlay": "contracts/p1/scheduler-profile-multistream-overlay.v1alpha1-draft.md",
    "scheduler_wire_golden": (
        "contracts/p1/fixtures/scheduler-profile-v1alpha1/scheduler-wire-golden.json"
    ),
    "contract_verifier": "scripts/verify_scheduler_profile_contract.py",
    "contract_tests": "tests/test_scheduler_profile_contract.py",
    "contract_ci": ".github/workflows/scheduler-profiler-contracts.yml",
}
EXPECTED_RUNTIME_PROFILE = {
    "async_scheduling": False,
    "communication_mode": "none",
    "data_parallel_size": 1,
    "decode_context_parallel_size": 1,
    "device_count": 1,
    "device_id": 0,
    "distributed_executor_backend": "uni",
    "ec_transfer_connector_enabled": False,
    "eager_execution": True,
    "host_count": 1,
    "kv_transfer_connector_enabled": False,
    "max_concurrent_batches": 1,
    "max_in_flight_execution_steps": 1,
    "model_mode": "decoder_only_generation",
    "multimodal": False,
    "n": 1,
    "pipeline_parallel_size": 1,
    "process_role": "engine_core",
    "prompt_count": 1,
    "rank_id": 0,
    "speculative_decoding": False,
    "tensor_parallel_size": 1,
}

COMMON = {
    "schema_version",
    "record_type",
    "scheduler_shard_id",
}
SCOPE = COMMON | {
    "experiment_run_id",
    "server_instance_id",
    "process_instance_id",
    "process_role",
    "profile_stream",
}
DATA_COMMON = COMMON | {"record_seq"}
FIELDS_BY_RECORD_TYPE = {
    "scheduler_start": SCOPE
    | {
        "started_monotonic_ns",
        "clock_source",
        "clock_domain_id",
        "runtime_core_commit",
        "device_plugin_commit",
        "parent_protocol_commit",
        "scheduler_profile_contract_sha256",
        "scheduler_profile_config_sha256",
        "multistream_overlay_sha256",
        "runtime_profile_id",
        "limits",
    },
    "schedule_cycle": DATA_COMMON
    | {
        "cycle_seq",
        "schedule_cycle_id",
        "logical_batch_id",
        "cycle_start_monotonic_ns",
        "cycle_end_monotonic_ns",
        "cycle_outcome",
        "waiting_engine_request_count_before",
        "running_engine_request_count_before",
        "waiting_engine_request_count_after",
        "running_engine_request_count_after",
        "configured_batched_token_budget",
        "effective_batched_token_budget",
        "configured_active_sequence_cap",
        "effective_active_sequence_cap",
        "token_budget_summary",
        "active_sequence_cap_summary",
    },
    "logical_batch": DATA_COMMON
    | {
        "batch_seq",
        "logical_batch_id",
        "schedule_cycle_id",
        "execution_step_id",
        "logical_batch_kind",
        "scheduled_token_count",
        "scheduled_engine_request_count",
        "prefill_token_count",
        "decode_token_count",
        "runtime_device_relation_candidate_eligible",
    },
    "execution_step_start": DATA_COMMON
    | {
        "execution_step_seq",
        "execution_step_id",
        "logical_batch_id",
        "dispatch_monotonic_ns",
        "dispatch_kind",
    },
    "execution_step_end": DATA_COMMON
    | {
        "execution_step_seq",
        "execution_step_id",
        "logical_batch_id",
        "final_result_monotonic_ns",
        "execution_outcome",
        "sampling_status",
    },
    "clock_bridge_sample": DATA_COMMON
    | {
        "sample_sequence",
        "clock_domain_id",
        "monotonic_before_ns",
        "realtime_ns",
        "monotonic_after_ns",
    },
    "loss_interval": COMMON
    | {
        "loss_interval_seq",
        "loss_interval_id",
        "reason",
        "first_dropped_record_seq",
        "last_dropped_record_seq",
        "dropped_count",
        "schedule_cycle_count",
        "logical_batch_count",
        "execution_step_start_count",
        "execution_step_end_count",
        "clock_bridge_sample_count",
        "first_observed_monotonic_ns",
        "last_observed_monotonic_ns",
    },
    "scheduler_summary": SCOPE
    | {
        "ended_monotonic_ns",
        "attempted_data_count",
        "written_schedule_cycle_count",
        "written_logical_batch_count",
        "written_execution_step_start_count",
        "written_execution_step_end_count",
        "written_clock_bridge_sample_count",
        "written_loss_interval_count",
        "dropped_data_count",
        "dropped_control_count",
        "first_data_record_seq",
        "last_data_record_seq",
        "writer_failure_count",
        "close_outcome",
        "content_sha256",
    },
}

TOKEN_BUCKETS = [
    (queue, mode)
    for queue in ("running", "waiting", "skipped_waiting")
    for mode in ("not_limited", "clipped", "stopped_no_chunk")
]
CAP_BUCKETS = [
    (queue, mode)
    for queue in ("running", "waiting", "skipped_waiting")
    for mode in ("not_limited", "stopped_at_cap")
]
SUMMARY_FIELDS = {
    "constraint_id",
    "gate_status",
    "not_evaluated_reason",
    "evaluated_count",
    "accounted_count",
    "unclassified_count",
    "buckets",
    "first_unclassified_witness",
}
BUCKET_FIELDS = {"queue", "mode", "count", "first_witness"}
TOKEN_WITNESS_FIELDS = {
    "evaluation_ordinal",
    "candidate_tokens_at_gate",
    "token_budget_before_at_gate",
    "granted_tokens_at_budget_gate",
    "running_count_at_budget_gate",
    "waiting_count_at_budget_gate",
    "effective_cap_at_budget_gate",
}
CAP_WITNESS_FIELDS = {
    "evaluation_ordinal",
    "cap_gate_waiting_count",
    "token_budget_at_cap_gate",
    "running_count_at_cap_gate",
    "effective_cap_at_gate",
}


class ContractError(ValueError):
    """A stable contract-verification error."""


def _reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate_member:{key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate
    )
    if not isinstance(value, dict):
        raise ContractError(f"not_object:{path}")
    return value


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_scalar(value: Any) -> None:
    if value is None or isinstance(value, (str, bool)):
        if isinstance(value, str) and any(0xD800 <= ord(ch) <= 0xDFFF for ch in value):
            raise ContractError("lone_surrogate")
        return
    if type(value) is int and -SAFE_INTEGER_MAX <= value <= 2**64 - 1:
        return
    raise ContractError("unsupported_jcs_value")


def _utf16_key(value: str) -> bytes:
    _validate_scalar(value)
    return value.encode("utf-16-be")


def canonicalize(value: Any) -> bytes:
    """RFC 8785 ordering/escaping with the wire contract's exact integers."""
    if isinstance(value, dict):
        members = []
        for key in sorted(value, key=_utf16_key):
            if not isinstance(key, str):
                raise ContractError("non_string_member")
            encoded_key = json.dumps(key, ensure_ascii=False, separators=(",", ":"))
            members.append(encoded_key.encode() + b":" + canonicalize(value[key]))
        return b"{" + b",".join(members) + b"}"
    if isinstance(value, list):
        return b"[" + b",".join(canonicalize(item) for item in value) + b"]"
    _validate_scalar(value)
    if value is None:
        return b"null"
    if value is True:
        return b"true"
    if value is False:
        return b"false"
    if type(value) is int:
        return str(value).encode("ascii")
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def _exact_keys(value: Any, expected: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ContractError(f"invalid_members:{name}")
    return value


def _uint(value: Any, bits: int, name: str) -> int:
    if type(value) is not int or not 0 <= value <= 2**bits - 1:
        raise ContractError(f"invalid_uint{bits}:{name}")
    return value


def _hex(value: Any, pattern: re.Pattern[str], name: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ContractError(f"invalid_identity:{name}")
    return value


def _bounded_string(value: Any, name: str, minimum: int = 1, maximum: int = 128) -> str:
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        raise ContractError(f"invalid_string:{name}")
    _validate_scalar(value)
    return value


def _validate_canonical_id(
    value: Any,
    scheduler_shard_id: str,
    kind: str,
    sequence: int,
    name: str,
) -> str:
    expected = f"{scheduler_shard_id}:{kind}:{sequence}"
    if not isinstance(value, str) or value != expected or len(value) > 96:
        raise ContractError(f"invalid_canonical_id:{name}")
    return value


def _validate_witness(
    value: Any, fields: set[str], name: str, unclassified: bool = False
) -> None:
    expected = fields | ({"reason_code"} if unclassified else set())
    witness = _exact_keys(value, expected, name)
    for key, item in witness.items():
        if key == "reason_code":
            if item not in {"unmapped_branch", "invalid_observation"}:
                raise ContractError("invalid_unclassified_reason")
        elif key in {
            "candidate_tokens_at_gate",
            "token_budget_before_at_gate",
            "granted_tokens_at_budget_gate",
            "token_budget_at_cap_gate",
        }:
            _uint(item, 64, key)
        else:
            _uint(item, 32, key)


def validate_constraint_summary(value: Any, token: bool) -> None:
    summary = _exact_keys(value, SUMMARY_FIELDS, "constraint_summary")
    constraint = "batched_token_budget" if token else "active_sequence_cap"
    if summary["constraint_id"] != constraint:
        raise ContractError("invalid_constraint_id")
    status = summary["gate_status"]
    if status not in {"evaluated", "not_evaluated", "missing"}:
        raise ContractError("invalid_gate_status")
    reason = summary["not_evaluated_reason"]
    if reason is not None and reason not in {
        "no_candidates",
        "gate_not_reached",
        "constraint_disabled",
        "not_applicable",
    }:
        raise ContractError("invalid_not_evaluated_reason")
    evaluated = _uint(summary["evaluated_count"], 32, "evaluated_count")
    accounted = _uint(summary["accounted_count"], 32, "accounted_count")
    unclassified = _uint(summary["unclassified_count"], 32, "unclassified_count")
    expected_buckets = TOKEN_BUCKETS if token else CAP_BUCKETS
    witness_fields = TOKEN_WITNESS_FIELDS if token else CAP_WITNESS_FIELDS
    buckets = summary["buckets"]
    if not isinstance(buckets, list) or len(buckets) != len(expected_buckets):
        raise ContractError("invalid_bucket_count")
    observed = []
    bucket_total = 0
    for bucket_value in buckets:
        bucket = _exact_keys(bucket_value, BUCKET_FIELDS, "constraint_bucket")
        observed.append((bucket["queue"], bucket["mode"]))
        count = _uint(bucket["count"], 32, "bucket_count")
        bucket_total += count
        if (count == 0) != (bucket["first_witness"] is None):
            raise ContractError("bucket_witness_presence")
        if count:
            _validate_witness(bucket["first_witness"], witness_fields, "first_witness")
    if observed != expected_buckets:
        raise ContractError("invalid_bucket_order")
    if evaluated != accounted + unclassified or accounted != bucket_total:
        raise ContractError("constraint_balance")
    if unclassified:
        _validate_witness(
            summary["first_unclassified_witness"],
            witness_fields,
            "unclassified_witness",
            True,
        )
    elif summary["first_unclassified_witness"] is not None:
        raise ContractError("unexpected_unclassified_witness")
    if status == "evaluated" and (evaluated == 0 or reason is not None):
        raise ContractError("evaluated_state")
    if status == "not_evaluated" and (evaluated != 0 or reason is None):
        raise ContractError("not_evaluated_state")
    if status == "missing" and (evaluated != 0 or reason is not None):
        raise ContractError("missing_state")


def validate_record(record: Any, max_bytes: int) -> None:
    if not isinstance(record, dict):
        raise ContractError("record_not_object")
    record_type = record.get("record_type")
    if record_type not in FIELDS_BY_RECORD_TYPE:
        raise ContractError("invalid_record_type")
    _exact_keys(record, FIELDS_BY_RECORD_TYPE[record_type], record_type)
    if record["schema_version"] != "rlp.scheduler/v1alpha1":
        raise ContractError("invalid_schema")
    scheduler_shard_id = record["scheduler_shard_id"]
    if not isinstance(scheduler_shard_id, str) or SHARD_ID.fullmatch(
        scheduler_shard_id
    ) is None:
        raise ContractError("invalid_scheduler_shard_id")
    if "record_seq" in record:
        _uint(record["record_seq"], 64, "record_seq")
    if len(canonicalize(record)) + 1 > max_bytes:
        raise ContractError("record_too_large")

    if record_type == "scheduler_start":
        for key in (
            "experiment_run_id",
            "server_instance_id",
            "process_instance_id",
        ):
            if not isinstance(record[key], str) or OPAQUE_ID.fullmatch(record[key]) is None:
                raise ContractError(f"invalid_scope_id:{key}")
        if record["process_role"] != "engine_core":
            raise ContractError("invalid_process_role")
        if record["profile_stream"] != "scheduler":
            raise ContractError("invalid_profile_stream")
        _uint(record["started_monotonic_ns"], 64, "started_monotonic_ns")
        if record["clock_source"] != "CLOCK_MONOTONIC":
            raise ContractError("invalid_clock_source")
        _hex(record["clock_domain_id"], HEX32, "clock_domain_id")
        for key in (
            "runtime_core_commit",
            "device_plugin_commit",
            "parent_protocol_commit",
        ):
            _hex(record[key], HEX40, key)
        for key in (
            "scheduler_profile_contract_sha256",
            "scheduler_profile_config_sha256",
            "multistream_overlay_sha256",
        ):
            _hex(record[key], HEX64, key)
        profile_id = _bounded_string(
            record["runtime_profile_id"], "runtime_profile_id", maximum=96
        )
        if not profile_id.isascii() or not profile_id.isprintable():
            raise ContractError("invalid_runtime_profile_id")
        if not isinstance(record["limits"], dict):
            raise ContractError("invalid_start_limits")
    elif record_type == "schedule_cycle":
        cycle_seq = _uint(record["cycle_seq"], 64, "cycle_seq")
        _validate_canonical_id(
            record["schedule_cycle_id"],
            scheduler_shard_id,
            "cycle",
            cycle_seq,
            "schedule_cycle_id",
        )
        if not isinstance(record["logical_batch_id"], str):
            raise ContractError("invalid_logical_batch_id")
        if record["cycle_outcome"] not in {"completed", "failed"}:
            raise ContractError("invalid_cycle_outcome")
        if _uint(record["cycle_end_monotonic_ns"], 64, "cycle_end") < _uint(
            record["cycle_start_monotonic_ns"], 64, "cycle_start"
        ):
            raise ContractError("inverted_cycle")
        for key in (
            "waiting_engine_request_count_before",
            "running_engine_request_count_before",
            "waiting_engine_request_count_after",
            "running_engine_request_count_after",
            "configured_active_sequence_cap",
            "effective_active_sequence_cap",
        ):
            _uint(record[key], 32, key)
        for key in (
            "configured_batched_token_budget",
            "effective_batched_token_budget",
        ):
            _uint(record[key], 64, key)
        validate_constraint_summary(record["token_budget_summary"], True)
        validate_constraint_summary(record["active_sequence_cap_summary"], False)
    elif record_type == "logical_batch":
        batch_seq = _uint(record["batch_seq"], 64, "batch_seq")
        _validate_canonical_id(
            record["logical_batch_id"],
            scheduler_shard_id,
            "batch",
            batch_seq,
            "logical_batch_id",
        )
        for key in ("schedule_cycle_id", "execution_step_id"):
            if not isinstance(record[key], str):
                raise ContractError(f"invalid_relation_id:{key}")
        scheduled = _uint(record["scheduled_token_count"], 64, "scheduled_token_count")
        prefill = _uint(record["prefill_token_count"], 64, "prefill_token_count")
        decode = _uint(record["decode_token_count"], 64, "decode_token_count")
        request_count = _uint(
            record["scheduled_engine_request_count"],
            32,
            "scheduled_engine_request_count",
        )
        if scheduled != prefill + decode:
            raise ContractError("batch_token_balance")
        if record["logical_batch_kind"] == "work":
            if (
                scheduled == 0
                or request_count == 0
                or record["runtime_device_relation_candidate_eligible"] is not True
            ):
                raise ContractError("invalid_work_batch")
        elif record["logical_batch_kind"] == "empty_control":
            if (
                scheduled != 0
                or request_count != 0
                or record["runtime_device_relation_candidate_eligible"] is not False
            ):
                raise ContractError("invalid_empty_control_batch")
        else:
            raise ContractError("invalid_batch_kind")
    elif record_type == "execution_step_start":
        step_seq = _uint(record["execution_step_seq"], 64, "execution_step_seq")
        _validate_canonical_id(
            record["execution_step_id"],
            scheduler_shard_id,
            "step",
            step_seq,
            "execution_step_id",
        )
        if not isinstance(record["logical_batch_id"], str):
            raise ContractError("invalid_relation_id:logical_batch_id")
        if record["dispatch_kind"] != "uniproc_execute_model":
            raise ContractError("invalid_execution_start_profile")
        _uint(record["dispatch_monotonic_ns"], 64, "dispatch_monotonic_ns")
    elif record_type == "execution_step_end":
        step_seq = _uint(record["execution_step_seq"], 64, "execution_step_seq")
        _validate_canonical_id(
            record["execution_step_id"],
            scheduler_shard_id,
            "step",
            step_seq,
            "execution_step_id",
        )
        if not isinstance(record["logical_batch_id"], str):
            raise ContractError("invalid_relation_id:logical_batch_id")
        _uint(record["final_result_monotonic_ns"], 64, "final_result_monotonic_ns")
        if record["execution_outcome"] not in {"completed", "failed", "cancelled"}:
            raise ContractError("invalid_execution_outcome")
        if record["sampling_status"] not in {"included_in_envelope", "not_applicable"}:
            raise ContractError("invalid_sampling_status")
    elif record_type == "clock_bridge_sample":
        _uint(record["sample_sequence"], 64, "sample_sequence")
        _hex(record["clock_domain_id"], HEX32, "clock_domain_id")
        before = _uint(record["monotonic_before_ns"], 64, "monotonic_before_ns")
        after = _uint(record["monotonic_after_ns"], 64, "monotonic_after_ns")
        _uint(record["realtime_ns"], 64, "realtime_ns")
        if before > after:
            raise ContractError("inverted_clock_bracket")
    elif record_type == "loss_interval":
        loss_seq = _uint(record["loss_interval_seq"], 64, "loss_interval_seq")
        _validate_canonical_id(
            record["loss_interval_id"],
            scheduler_shard_id,
            "loss",
            loss_seq,
            "loss_interval_id",
        )
        if record["reason"] not in {
            "serialization_failure",
            "queue_overflow",
            "writer_failure",
            "close_timeout",
        }:
            raise ContractError("invalid_loss_reason")
        first = _uint(
            record["first_dropped_record_seq"], 64, "first_dropped_record_seq"
        )
        last = _uint(record["last_dropped_record_seq"], 64, "last_dropped_record_seq")
        count = _uint(record["dropped_count"], 64, "dropped_count")
        type_sum = sum(
            _uint(record[key], 64, key)
            for key in (
                "schedule_cycle_count",
                "logical_batch_count",
                "execution_step_start_count",
                "execution_step_end_count",
                "clock_bridge_sample_count",
            )
        )
        if last < first or count != last - first + 1 or type_sum != count:
            raise ContractError("invalid_loss_balance")
        if _uint(record["last_observed_monotonic_ns"], 64, "loss_end") < _uint(
            record["first_observed_monotonic_ns"], 64, "loss_start"
        ):
            raise ContractError("inverted_loss_interval")
    elif record_type == "scheduler_summary":
        for key in (
            "experiment_run_id",
            "server_instance_id",
            "process_instance_id",
        ):
            if not isinstance(record[key], str) or OPAQUE_ID.fullmatch(record[key]) is None:
                raise ContractError(f"invalid_scope_id:{key}")
        if record["process_role"] != "engine_core":
            raise ContractError("invalid_process_role")
        if record["profile_stream"] != "scheduler":
            raise ContractError("invalid_profile_stream")
        _uint(record["ended_monotonic_ns"], 64, "ended_monotonic_ns")
        attempted = _uint(record["attempted_data_count"], 64, "attempted_data_count")
        written = sum(
            _uint(record[key], 64, key)
            for key in (
                "written_schedule_cycle_count",
                "written_logical_batch_count",
                "written_execution_step_start_count",
                "written_execution_step_end_count",
                "written_clock_bridge_sample_count",
            )
        )
        dropped = _uint(record["dropped_data_count"], 64, "dropped_data_count")
        if attempted != written + dropped:
            raise ContractError("invalid_summary_balance")
        if attempted == 0:
            if (
                record["first_data_record_seq"] is not None
                or record["last_data_record_seq"] is not None
            ):
                raise ContractError("invalid_empty_summary_range")
        elif (
            record["first_data_record_seq"] != 0
            or record["last_data_record_seq"] != attempted - 1
        ):
            raise ContractError("invalid_summary_range")
        for key in (
            "written_loss_interval_count",
            "dropped_control_count",
            "writer_failure_count",
        ):
            _uint(record[key], 64, key)
        if record["close_outcome"] not in {"drained", "timeout", "writer_failure"}:
            raise ContractError("invalid_close_outcome")
        _hex(record["content_sha256"], HEX64, "content_sha256")


def _maximal_schedule_cycle(record: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(record)
    maximum_u32 = 2**32 - 1
    maximum_u64 = 2**64 - 1
    result.update(
        {
            "record_seq": maximum_u64,
            "cycle_seq": maximum_u64,
            "schedule_cycle_id": f"{record['scheduler_shard_id']}:cycle:{maximum_u64}",
            "cycle_start_monotonic_ns": maximum_u64,
            "cycle_end_monotonic_ns": maximum_u64,
            "waiting_engine_request_count_before": maximum_u32,
            "running_engine_request_count_before": maximum_u32,
            "waiting_engine_request_count_after": maximum_u32,
            "running_engine_request_count_after": maximum_u32,
            "configured_batched_token_budget": maximum_u64,
            "effective_batched_token_budget": maximum_u64,
            "configured_active_sequence_cap": maximum_u32,
            "effective_active_sequence_cap": maximum_u32,
        }
    )
    for summary, witness_fields in (
        (result["token_budget_summary"], TOKEN_WITNESS_FIELDS),
        (result["active_sequence_cap_summary"], CAP_WITNESS_FIELDS),
    ):
        buckets = summary["buckets"]
        summary["evaluated_count"] = maximum_u32
        summary["accounted_count"] = maximum_u32 - 1
        summary["unclassified_count"] = 1
        for index, bucket in enumerate(buckets):
            bucket["count"] = maximum_u32 - len(buckets) if index == 0 else 1
            bucket["first_witness"] = {
                key: maximum_u64
                if key
                in {
                    "candidate_tokens_at_gate",
                    "token_budget_before_at_gate",
                    "granted_tokens_at_budget_gate",
                    "token_budget_at_cap_gate",
                }
                else maximum_u32
                for key in witness_fields
            }
        summary["first_unclassified_witness"] = {
            **{
                key: maximum_u64
                if key
                in {
                    "candidate_tokens_at_gate",
                    "token_budget_before_at_gate",
                    "granted_tokens_at_budget_gate",
                    "token_budget_at_cap_gate",
                }
                else maximum_u32
                for key in witness_fields
            },
            "reason_code": "invalid_observation",
        }
    return result


def _validate_record_sequence_coverage(
    records: list[dict[str, Any]], summary: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    data = [record for record in records if "record_seq" in record]
    losses = [record for record in records if record["record_type"] == "loss_interval"]
    written_sequences = [record["record_seq"] for record in data]
    if written_sequences != sorted(set(written_sequences)):
        raise ContractError("wire_record_sequence_order")
    if [record["loss_interval_seq"] for record in losses] != list(range(len(losses))):
        raise ContractError("wire_loss_interval_sequence")

    segments = [(sequence, sequence) for sequence in written_sequences]
    dropped_count = 0
    for loss in losses:
        first = loss["first_dropped_record_seq"]
        last = loss["last_dropped_record_seq"]
        segments.append((first, last))
        dropped_count += loss["dropped_count"]
    if dropped_count != summary["dropped_data_count"]:
        raise ContractError("wire_loss_summary_mismatch")

    attempted = summary["attempted_data_count"]
    cursor = 0
    for first, last in sorted(segments):
        if first != cursor:
            raise ContractError("wire_record_sequence_coverage")
        cursor = last + 1
    if cursor != attempted:
        raise ContractError("wire_record_sequence_coverage")
    return data, losses


def validate_wire_golden(path: Path, config: dict[str, Any]) -> dict[str, Any]:
    payload = load_json(path)
    if payload.get("schema_version") != 1 or not isinstance(
        payload.get("records"), list
    ):
        raise ContractError("invalid_wire_fixture")
    records: list[dict[str, Any]] = []
    lines: list[bytes] = []
    for record in payload["records"]:
        line = canonicalize(record) + b"\n"
        validate_record(record, config["wire_limits"]["max_record_bytes_including_lf"])
        records.append(record)
        lines.append(line)
    if not records:
        raise ContractError("empty_wire_fixture")
    start_count = sum(record["record_type"] == "scheduler_start" for record in records)
    summary_count = sum(
        record["record_type"] == "scheduler_summary" for record in records
    )
    if start_count != 1 or summary_count != 1:
        raise ContractError("wire_control_cardinality")
    if (
        records[0]["record_type"] != "scheduler_start"
        or records[-1]["record_type"] != "scheduler_summary"
    ):
        raise ContractError("wire_control_order")
    start = records[0]
    if start["limits"] != config["wire_limits"]:
        raise ContractError("wire_start_limits_mismatch")
    expected_digests = {
        "scheduler_profile_contract_sha256": sha256_file(CONTRACT_PATH),
        "scheduler_profile_config_sha256": sha256_file(CONFIG_PATH),
        "multistream_overlay_sha256": sha256_file(OVERLAY_PATH),
    }
    if any(start[key] != digest for key, digest in expected_digests.items()):
        raise ContractError("wire_start_artifact_digest_mismatch")
    if any(
        record["clock_domain_id"] != start["clock_domain_id"]
        for record in records
        if record["record_type"] == "clock_bridge_sample"
    ):
        raise ContractError("clock_domain_mismatch")
    if any(
        record["scheduler_shard_id"] != start["scheduler_shard_id"]
        for record in records
    ):
        raise ContractError("wire_scope_mismatch")
    summary = records[-1]
    for key in (
        "experiment_run_id",
        "server_instance_id",
        "process_instance_id",
        "scheduler_shard_id",
        "process_role",
        "profile_stream",
    ):
        if summary[key] != start[key]:
            raise ContractError("wire_scope_mismatch")
    observed_types = {record["record_type"] for record in records}
    if observed_types != set(FIELDS_BY_RECORD_TYPE):
        raise ContractError("incomplete_record_type_golden")
    data, losses = _validate_record_sequence_coverage(records, summary)
    if len(losses) > config["wire_limits"]["max_loss_interval_records_per_shard"]:
        raise ContractError("wire_loss_interval_limit")
    cycles = {
        record["schedule_cycle_id"]: record
        for record in records
        if record["record_type"] == "schedule_cycle"
    }
    batches = {
        record["logical_batch_id"]: record
        for record in records
        if record["record_type"] == "logical_batch"
    }
    starts = {
        record["execution_step_id"]: record
        for record in records
        if record["record_type"] == "execution_step_start"
    }
    ends = {
        record["execution_step_id"]: record
        for record in records
        if record["record_type"] == "execution_step_end"
    }
    if (
        len(cycles)
        != sum(record["record_type"] == "schedule_cycle" for record in records)
        or len(batches)
        != sum(record["record_type"] == "logical_batch" for record in records)
        or len(starts)
        != sum(record["record_type"] == "execution_step_start" for record in records)
        or len(ends)
        != sum(record["record_type"] == "execution_step_end" for record in records)
    ):
        raise ContractError("duplicate_entity_id")
    for cycle in cycles.values():
        batch = batches.get(cycle["logical_batch_id"])
        if batch is None or batch["schedule_cycle_id"] != cycle["schedule_cycle_id"]:
            raise ContractError("cycle_batch_relation")
        step_id = batch["execution_step_id"]
        if (
            starts.get(step_id, {}).get("logical_batch_id") != batch["logical_batch_id"]
            or ends.get(step_id, {}).get("logical_batch_id")
            != batch["logical_batch_id"]
        ):
            raise ContractError("batch_execution_relation")
        dispatch = starts[step_id]["dispatch_monotonic_ns"]
        final_result = ends[step_id]["final_result_monotonic_ns"]
        if cycle["cycle_end_monotonic_ns"] > dispatch or dispatch > final_result:
            raise ContractError("invalid_cycle_execution_order")
    if not (len(cycles) == len(batches) == len(starts) == len(ends)):
        raise ContractError("non_bijective_cycle_batch_step_relation")
    open_steps: set[str] = set()
    for record in records:
        if record["record_type"] == "execution_step_start":
            if open_steps:
                raise ContractError("multiple_in_flight_steps")
            open_steps.add(record["execution_step_id"])
        elif record["record_type"] == "execution_step_end":
            if record["execution_step_id"] not in open_steps:
                raise ContractError("step_end_without_open_start")
            open_steps.remove(record["execution_step_id"])
    if open_steps:
        raise ContractError("unclosed_execution_step")
    actual_written = {
        "written_schedule_cycle_count": sum(
            record["record_type"] == "schedule_cycle" for record in data
        ),
        "written_logical_batch_count": sum(
            record["record_type"] == "logical_batch" for record in data
        ),
        "written_execution_step_start_count": sum(
            record["record_type"] == "execution_step_start" for record in data
        ),
        "written_execution_step_end_count": sum(
            record["record_type"] == "execution_step_end" for record in data
        ),
        "written_clock_bridge_sample_count": sum(
            record["record_type"] == "clock_bridge_sample" for record in data
        ),
        "written_loss_interval_count": sum(
            record["record_type"] == "loss_interval" for record in records
        ),
    }
    if any(summary[key] != value for key, value in actual_written.items()):
        raise ContractError("wire_summary_count_mismatch")
    content = b"".join(lines[:-1])
    if summary["content_sha256"] != hashlib.sha256(content).hexdigest():
        raise ContractError("wire_content_digest")
    maximal_cycle = _maximal_schedule_cycle(next(iter(cycles.values())))
    validate_record(
        maximal_cycle, config["wire_limits"]["max_record_bytes_including_lf"]
    )
    maximal_cycle_bytes = len(canonicalize(maximal_cycle)) + 1
    return {
        "records": len(records),
        "data_records": len(data),
        "max_encoded_record_bytes": max(len(line) for line in lines),
        "generated_maximal_cycle_bytes": maximal_cycle_bytes,
        "record_limit_bytes": config["wire_limits"]["max_record_bytes_including_lf"],
        "wire_bytes_sha256": hashlib.sha256(b"".join(lines)).hexdigest(),
        "fixture_sha256": sha256_file(path),
    }


def verify_config(config: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(
        config,
        {
            "artifact_kind",
            "artifact_status",
            "clock_bridge",
            "composition_boundary",
            "profile_stream",
            "runtime_profile",
            "schema_version",
            "wire_limits",
            "wire_schema",
        },
        "config",
    )
    limits = config["wire_limits"]
    if (
        config["artifact_kind"] != "scheduler_profile_config"
        or config["artifact_status"] != "owner_review_candidate"
        or config["schema_version"] != 1
        or config["profile_stream"] != "scheduler"
        or config["wire_schema"] != "rlp.scheduler/v1alpha1"
    ):
        raise ContractError("invalid_config_status")
    if config["runtime_profile"] != EXPECTED_RUNTIME_PROFILE:
        raise ContractError("invalid_runtime_profile")
    for key, value in limits.items():
        if key in {"shard_mode_octal", "shard_path_template", "shard_scope"}:
            if not isinstance(value, str) or not value:
                raise ContractError(f"invalid_wire_limit:{key}")
        elif type(value) is not int or value <= 0:
            raise ContractError(f"invalid_wire_limit:{key}")
    if limits["shard_mode_octal"] != "0600":
        raise ContractError("invalid_shard_mode")
    burst = (
        limits["max_cycle_rate_per_rolling_second"]
        * limits["max_writer_service_gap_ms"]
        // 1000
        * limits["max_data_records_per_cycle"]
        * limits["producer_safety_factor"]
        + limits["clock_bridge_records_per_writer_gap_max"]
    )
    if limits["data_capacity_records"] < burst:
        raise ContractError("insufficient_data_capacity")
    if (
        limits["reserved_capacity_records"]
        != limits["max_loss_interval_records_per_shard"]
    ):
        raise ContractError("loss_interval_reserve_mismatch")
    queued = (
        limits["data_capacity_records"] + limits["reserved_capacity_records"]
    ) * limits["max_record_bytes_including_lf"]
    if limits["max_queued_bytes"] != queued:
        raise ContractError("queued_byte_formula")
    cycles = (
        limits["max_formal_run_duration_s"]
        * limits["max_cycle_rate_per_rolling_second"]
    )
    if limits["max_cycles_in_formal_run"] != cycles:
        raise ContractError("formal_cycle_formula")
    records = (
        cycles * limits["max_data_records_per_cycle"]
        + limits["clock_bridge_max_records"]
        + limits["max_loss_interval_records_per_shard"]
        + 2
    )
    artifact = records * limits["max_record_bytes_including_lf"]
    if limits["artifact_bytes_max"] != artifact:
        raise ContractError("artifact_byte_formula")
    if (
        limits["disk_free_required_bytes"]
        != artifact + limits["disk_free_margin_bytes"]
    ):
        raise ContractError("disk_byte_formula")
    expected_clock_records = (
        limits["max_formal_run_duration_s"]
        * 1_000_000_000
        // config["clock_bridge"]["cadence_ns"]
        + 1
    )
    if limits["clock_bridge_max_records"] != expected_clock_records:
        raise ContractError("clock_record_formula")
    if (
        limits["max_batch_bytes"]
        > limits["max_batch_records"] * limits["max_record_bytes_including_lf"]
    ):
        raise ContractError("batch_byte_bound")
    boundary = _exact_keys(
        config["composition_boundary"],
        {
            "authority",
            "exact_requires_explicit_shared_producer_execution_id",
            "forbidden_identity_authorities",
            "profile_source_namespace_required",
            "relation_statuses",
            "timestamp_containment_maximum_status",
        },
        "composition_boundary",
    )
    if (
        boundary["authority"] != "experiment_repo_run_manifest/v1"
        or boundary["exact_requires_explicit_shared_producer_execution_id"] is not True
        or boundary["profile_source_namespace_required"] is not True
        or boundary["relation_statuses"]
        != ["exact", "correlated", "ambiguous", "unmatched", "unsupported"]
        or boundary["timestamp_containment_maximum_status"] != "correlated"
        or set(boundary["forbidden_identity_authorities"])
        != {
            "analyzer_run_id",
            "pid_context_across_profile_sources",
            "rank_device_time_similarity",
            "scheduler_selected_profile_database",
            "timestamp_proximity",
        }
    ):
        raise ContractError("invalid_composition_boundary")
    return {
        "burst_required_records": burst,
        "artifact_records_max": records,
        "artifact_bytes_max": artifact,
    }


def verify_candidate(candidate: dict[str, Any]) -> dict[str, str]:
    _exact_keys(
        candidate,
        {
            "acceptance_items",
            "analyzer_boundary",
            "artifact_kind",
            "artifact_status",
            "base_contracts",
            "experiment_composition_dependency",
            "gate_effects_before_owner_approval",
            "owner_approval_requirement",
            "parent_architecture",
            "pr_i0_authority",
            "proposed_artifacts",
            "schema_version",
        },
        "approval_candidate",
    )
    if (
        candidate["artifact_kind"] != "scheduler_profile_pr_c1_approval_candidate"
        or candidate["artifact_status"] != "owner_review_required"
        or candidate["schema_version"] != 1
    ):
        raise ContractError("invalid_candidate_status")
    parent = _exact_keys(
        candidate["parent_architecture"],
        {
            "architecture_path",
            "architecture_sha256",
            "overlay_path",
            "overlay_sha256",
            "pull_request",
            "repository",
            "status",
        },
        "parent_architecture",
    )
    if (
        parent["repository"] != "intellistream/vllm-request-lifecycle-profiler-plugin"
        or parent["pull_request"] != 14
        or parent["status"] != "route_b_architecture_review_candidate"
        or parent["architecture_path"] != ARCHITECTURE_PATH.relative_to(ROOT).as_posix()
        or parent["overlay_path"]
        != ARCHITECTURE_OVERLAY_PATH.relative_to(ROOT).as_posix()
        or parent["architecture_sha256"] != sha256_file(ARCHITECTURE_PATH)
        or parent["overlay_sha256"] != sha256_file(ARCHITECTURE_OVERLAY_PATH)
    ):
        raise ContractError("invalid_parent_architecture_authority")
    i0 = _exact_keys(
        candidate["pr_i0_authority"],
        {"pull_request", "repository", "status"},
        "pr_i0_authority",
    )
    if (
        i0["repository"] != "intellistream/ascend-llm-realworkload-prof"
        or i0["pull_request"] != 30
        or i0["status"] != "route_b_revision_required_before_owner_approval"
    ):
        raise ContractError("invalid_pr_i0_authority")
    analyzer = _exact_keys(
        candidate["analyzer_boundary"],
        {
            "cross_db_identity_authority",
            "default_source_boundary",
            "pid_context_scope",
            "repository",
            "scheduler_ingestion_required",
        },
        "analyzer_boundary",
    )
    if (
        analyzer["repository"] != "vLLM-HUST/vllm-hust-perf-analyzer"
        or analyzer["default_source_boundary"] != "one_profile_source"
        or analyzer["cross_db_identity_authority"] is not False
        or analyzer["pid_context_scope"] != "single_source_diagnostic_only"
        or analyzer["scheduler_ingestion_required"] is not False
    ):
        raise ContractError("invalid_analyzer_boundary")
    composition = _exact_keys(
        candidate["experiment_composition_dependency"],
        {"pull_request", "repository", "status"},
        "experiment_composition_dependency",
    )
    if (
        composition["repository"] != "intellistream/ascend-llm-realworkload-prof"
        or composition["pull_request"] != 30
        or composition["status"] != "route_b_manifest_and_composer_required"
    ):
        raise ContractError("invalid_experiment_composition_dependency")
    base_contracts = candidate["base_contracts"]
    if not isinstance(base_contracts, list) or len(base_contracts) != 4:
        raise ContractError("invalid_base_contract_roster")
    expected_base_paths = {
        "contracts/p0/runtime/minimum-runtime-contract.v0-draft.md",
        "contracts/p0/runtime/phase-taxonomy.v0-draft.md",
        "contracts/p0/p0-manifest.json",
        "contracts/p0/owner-freeze-approval.json",
    }
    if {
        item.get("path") for item in base_contracts if isinstance(item, dict)
    } != expected_base_paths:
        raise ContractError("invalid_base_contract_roster")
    for item in base_contracts:
        _exact_keys(item, {"path", "sha256", "status"}, "base_contract")
        if item["status"] != "owner_frozen":
            raise ContractError("unfrozen_base_contract")
        if sha256_file(ROOT / item["path"]) != item["sha256"]:
            raise ContractError(f"base_contract_digest_mismatch:{item['path']}")
    if candidate["acceptance_items"] != list(range(1, 8)):
        raise ContractError("invalid_acceptance_items")
    if (
        not isinstance(candidate["owner_approval_requirement"], str)
        or "exact SHA-256" not in candidate["owner_approval_requirement"]
    ):
        raise ContractError("invalid_owner_approval_requirement")
    observed: dict[str, str] = {}
    artifacts = candidate.get("proposed_artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ContractError("missing_candidate_artifacts")
    for artifact in artifacts:
        _exact_keys(artifact, {"path", "role", "sha256"}, "candidate_artifact")
        if EXPECTED_CANDIDATE_ARTIFACTS.get(artifact["role"]) != artifact["path"]:
            raise ContractError(f"unexpected_candidate_artifact:{artifact['role']}")
        if artifact["role"] in observed:
            raise ContractError(f"duplicate_candidate_artifact:{artifact['role']}")
        _hex(artifact["sha256"], HEX64, f"artifact.{artifact['role']}")
        path = ROOT / artifact["path"]
        digest = sha256_file(path)
        if digest != artifact["sha256"]:
            raise ContractError(f"candidate_digest_mismatch:{artifact['path']}")
        observed[artifact["role"]] = digest
    if observed.keys() != EXPECTED_CANDIDATE_ARTIFACTS.keys():
        raise ContractError("incomplete_candidate_artifact_roster")
    effects = candidate.get("gate_effects_before_owner_approval", {})
    required_false = {
        "scheduler_wire_approved",
        "multistream_overlay_approved",
        "pr_i1_implementation_authorized",
        "pr_i2_runtime_hooks_authorized",
        "runtime_activation_authorized",
        "formal_profiler_collection_authorized",
        "scientific_evidence",
        "merge_authorized",
    }
    if set(effects) != required_false or any(
        value is not False for value in effects.values()
    ):
        raise ContractError("candidate_gate_overclaim")
    return observed


def verify() -> dict[str, Any]:
    config = load_json(CONFIG_PATH)
    candidate = load_json(CANDIDATE_PATH)
    report = {
        "config": verify_config(config),
        "candidate_artifacts": verify_candidate(candidate),
        "wire_golden": validate_wire_golden(
            FIXTURES / "scheduler-wire-golden.json", config
        ),
    }
    report["valid"] = True
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        report = verify()
    except (
        ContractError,
        KeyError,
        OSError,
        UnicodeError,
        json.JSONDecodeError,
    ) as exc:
        report = {"valid": False, "error": str(exc)}
        if args.json:
            print(json.dumps(report, sort_keys=True, separators=(",", ":")))
        else:
            print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        print("PASS: scheduler profile PR-C1 contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
