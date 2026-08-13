"""Strict wire builders for the optional KV-recovery profile shard."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from vllm_request_lifecycle_profiler.runtime_protocol import (
    CLOSE_TIMEOUT_MS,
    DATA_CAPACITY_RECORDS,
    MAX_BATCH_BYTES,
    MAX_BATCH_RECORDS,
    MAX_QUEUED_BYTES,
    RESERVED_CAPACITY_RECORDS,
    SCHEMA_VERSION,
    WRITE_INTERVAL_MS,
    RuntimeProvenance,
    canonical_json_line,
)

PROFILE_ID = "rlp.kv-recovery/v1alpha1"
COMMUNICATION_MODE = "issue2:kv-recovery-v1alpha1"

MAX_PROFILE_DATA_RECORDS = 4096
MAX_PROFILE_RECORD_BYTES = 4096
MAX_METADATA_BYTES = 1024
MAX_LOGICAL_BLOCKS_PER_BLOCK_SET = 4096
MAX_BLOCK_ROWS_PER_CHUNK = 64
MAX_TRANSFER_RECORDS_PER_LIFECYCLE = 4096
MAX_TRANSFER_IDS_PER_WAIT_SET = 4096
MAX_WAIT_SET_ROWS_PER_CHUNK = 64
MAX_WAIT_SETS_PER_PROCESS_SHARD = 64
MAX_REQUEUE_OBSERVATIONS_PER_EPISODE = 64
MAX_RUNTIME_REQUEST_ID_BYTES = 128

PROFILE_LIMITS: Mapping[str, int | str] = {
    "data_capacity_records": DATA_CAPACITY_RECORDS,
    "reserved_capacity_records": RESERVED_CAPACITY_RECORDS,
    "max_record_bytes": MAX_PROFILE_RECORD_BYTES,
    "max_queued_bytes": MAX_QUEUED_BYTES,
    "max_batch_records": MAX_BATCH_RECORDS,
    "max_batch_bytes": MAX_BATCH_BYTES,
    "write_interval_ms": WRITE_INTERVAL_MS,
    "close_timeout_ms": CLOSE_TIMEOUT_MS,
    "max_metadata_bytes": MAX_METADATA_BYTES,
    "max_logical_blocks_per_block_set": MAX_LOGICAL_BLOCKS_PER_BLOCK_SET,
    "max_block_rows_per_chunk": MAX_BLOCK_ROWS_PER_CHUNK,
    "max_transfer_records_per_lifecycle": MAX_TRANSFER_RECORDS_PER_LIFECYCLE,
    "max_transfer_ids_per_wait_set": MAX_TRANSFER_IDS_PER_WAIT_SET,
    "max_wait_set_rows_per_chunk": MAX_WAIT_SET_ROWS_PER_CHUNK,
    "max_wait_sets_per_process_shard": MAX_WAIT_SETS_PER_PROCESS_SHARD,
    "max_requeue_observations_per_episode": (MAX_REQUEUE_OBSERVATIONS_PER_EPISODE),
    "max_runtime_request_id_bytes": MAX_RUNTIME_REQUEST_ID_BYTES,
    "shard_ownership": "one_process_one_append_only_profile_shard",
}

ProfileRecordType = Literal[
    "block_set_chunk", "wait_set_chunk", "transfer_event", "recovery_event"
]
LossReason = Literal[
    "serialization_failure", "queue_overflow", "writer_failure", "close_timeout"
]

_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_EVENT_ID = re.compile(r"^[0-9a-f]{32}:e:(0|[1-9][0-9]{0,19})$")
_PROFILE_RECORD_ID = re.compile(r"^[0-9a-f]{32}:k:(0|[1-9][0-9]{0,19})$")
_TRANSFER_ID = re.compile(r"^[0-9a-f]{32}:t:(0|[1-9][0-9]{0,19})$")
_UINT32_MAX = 2**32 - 1
_UINT64_MAX = 2**64 - 1


@dataclass(frozen=True)
class KVRecoveryProfileConfig:
    """Complete immutable inputs needed before the paired writer starts."""

    run_id: str
    spec_name: str = "TieringOffloadingSpec"
    profile_id: str = PROFILE_ID
    communication_mode: str = COMMUNICATION_MODE
    implementation_family: str = "runtime_core_offloading_connector"
    connector_name: str = "OffloadingConnector"
    rank: int = 0
    world_size: int = 1

    def __post_init__(self) -> None:
        _require_hex(self.run_id, 32, "run_id")
        if self.profile_id != PROFILE_ID:
            raise ValueError("profile_id is not supported")
        if self.communication_mode != COMMUNICATION_MODE:
            raise ValueError("communication_mode is not supported")
        if self.implementation_family != "runtime_core_offloading_connector":
            raise ValueError("implementation_family is outside profile v1alpha1")
        if self.connector_name != "OffloadingConnector":
            raise ValueError("connector_name is outside profile v1alpha1")
        if self.spec_name != "TieringOffloadingSpec":
            raise ValueError("spec_name is not supported")
        if self.rank != 0 or self.world_size != 1:
            raise ValueError("profile v1alpha1 requires rank=0 and world_size=1")


@dataclass(frozen=True)
class ProfileRecordRef:
    record_type: ProfileRecordType
    record_seq: int
    record_id: str
    timestamp_ns: int
    record: Mapping[str, object]


@dataclass(frozen=True)
class ProfileRecord:
    record_type: ProfileRecordType
    record_seq: int
    record_id: str
    timestamp_ns: int
    fields: Mapping[str, object]


@dataclass(frozen=True)
class ProfileLossInterval:
    reason: LossReason
    first_record_seq: int
    last_record_seq: int
    counts: Mapping[ProfileRecordType, int]
    first_timestamp_ns: int
    last_timestamp_ns: int

    @property
    def dropped_count(self) -> int:
        return self.last_record_seq - self.first_record_seq + 1


def _is_uint(value: object, maximum: int) -> bool:
    return type(value) is int and 0 <= value <= maximum


def _require_uint(value: object, maximum: int, field_name: str) -> int:
    if not _is_uint(value, maximum):
        raise ValueError(f"{field_name} is outside its unsigned integer domain")
    return value


def _require_ascii(
    value: object, field_name: str, *, minimum: int = 1, maximum: int = 128
) -> str:
    if (
        not isinstance(value, str)
        or not value.isascii()
        or not value.isprintable()
        or not minimum <= len(value.encode("ascii")) <= maximum
    ):
        raise ValueError(f"{field_name} must be bounded printable ASCII")
    return value


def _require_hex(value: object, length: int, field_name: str) -> str:
    pattern = {32: _HEX32, 40: _HEX40, 64: _HEX64}[length]
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(f"{field_name} must be {length} lowercase hexadecimal chars")
    return value


def _require_nullable_hex(value: object, length: int, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_hex(value, length, field_name)


def _require_event_id(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _EVENT_ID.fullmatch(value):
        raise ValueError(f"{field_name} must be a canonical base event ID")
    return value


def _require_nullable_event_id(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_event_id(value, field_name)


def _require_profile_record_id(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _PROFILE_RECORD_ID.fullmatch(value):
        raise ValueError(f"{field_name} must be a canonical profile record ID")
    return value


def _require_nullable_profile_record_id(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_profile_record_id(value, field_name)


def _require_exact_fields(
    fields: Mapping[str, object], required: set[str], record_type: str
) -> None:
    actual = set(fields)
    if actual != required:
        missing = sorted(required - actual)
        extra = sorted(actual - required)
        raise ValueError(
            f"{record_type} fields differ from the closed roster; "
            f"missing={missing}, extra={extra}"
        )


def _bounded_line(record: Mapping[str, object]) -> bytes:
    raw = canonical_json_line(record)
    if len(raw) > MAX_PROFILE_RECORD_BYTES:
        raise ValueError("profile record exceeds max_record_bytes")
    return raw


def profile_record_line(record: Mapping[str, object]) -> bytes:
    """Encode an already-built profile record under the frozen byte limit."""

    return _bounded_line(record)


def build_profile_start_record(
    *,
    process_uuid: str,
    pid: int,
    started_timestamp_ns: int,
    clock_domain_id: str,
    provenance: RuntimeProvenance,
    config: KVRecoveryProfileConfig,
) -> dict[str, object]:
    record = {
        "schema": config.profile_id,
        "record_type": "profile_start",
        "process_uuid": _require_hex(process_uuid, 32, "process_uuid"),
        "pid": _require_uint(pid, _UINT32_MAX, "pid"),
        "started_timestamp_ns": _require_uint(
            started_timestamp_ns, _UINT64_MAX, "started_timestamp_ns"
        ),
        "clock_source": "CLOCK_MONOTONIC",
        "clock_domain_id": _require_hex(clock_domain_id, 32, "clock_domain_id"),
        "profile_id": config.profile_id,
        "run_id": config.run_id,
        "profiler_parent_commit": provenance.profiler_parent_commit,
        "runtime_core_commit": provenance.runtime_core_commit,
        "device_plugin_commit": provenance.device_plugin_commit,
        "base_trace_schema": SCHEMA_VERSION,
        "rank": config.rank,
        "world_size": config.world_size,
        "implementation_family": config.implementation_family,
        "connector_name": config.connector_name,
        "spec_name": config.spec_name,
        "communication_mode": config.communication_mode,
        "limits": dict(PROFILE_LIMITS),
    }
    _bounded_line(record)
    return record


_REQUEST_FIELDS = {
    "trace_id",
    "engine_lifecycle_id",
    "runtime_request_id",
    "request_id_kind",
    "sample_index",
    "recovery_epoch",
    "episode_id",
}
_BLOCK_FIELDS = {
    "block_set_id",
    "chunk_index",
    "chunk_count",
    "total_block_count",
    "blocks",
}
_WAIT_FIELDS = {
    "operation",
    "wait_set_id",
    "chunk_index",
    "chunk_count",
    "total_transfer_count",
    "transfer_ids",
}
_TRANSFER_FIELDS = {
    "transfer_id",
    "connector_job_id",
    "rank",
    "world_size",
    "operation",
    "direction",
    "src_medium",
    "dst_medium",
    "block_set_id",
    "transfer_phase",
    "bytes_moved",
    "device_duration_ns",
    "success",
    "failure_code",
}
_RECOVERY_FIELDS = {
    "stage",
    "occurrence",
    "base_event_id",
    "base_admission_started_event_id",
    "from_profile_event_id",
    "transfer_id",
    "block_set_id",
    "bytes_moved",
    "requeue_reason",
    "compute_kind",
    "child_observation_kind",
    "base_association_kind",
    "base_association_evidence",
    "request_status_before",
    "request_status_after",
}


def _validate_request_fields(fields: Mapping[str, object]) -> None:
    trace_id = _require_hex(fields["trace_id"], 32, "trace_id")
    sample_index = _require_uint(fields["sample_index"], _UINT32_MAX, "sample_index")
    if sample_index != 0:
        raise ValueError("profile v1alpha1 requires sample_index=0")
    if fields["engine_lifecycle_id"] != f"{trace_id}:e:0":
        raise ValueError("engine_lifecycle_id does not match trace/sample")
    _require_ascii(
        fields["runtime_request_id"],
        "runtime_request_id",
        maximum=MAX_RUNTIME_REQUEST_ID_BYTES,
    )
    if fields["request_id_kind"] != "engine_internal":
        raise ValueError("request_id_kind must be engine_internal")
    epoch = fields["recovery_epoch"]
    episode_id = fields["episode_id"]
    if epoch is None:
        if episode_id is not None:
            raise ValueError("episode_id must be null when recovery_epoch is null")
    else:
        epoch = _require_uint(epoch, _UINT32_MAX, "recovery_epoch")
        if epoch < 1:
            raise ValueError("recovery_epoch must be positive")
        expected = f"{fields['engine_lifecycle_id']}:k:{epoch}"
        if episode_id != expected:
            raise ValueError("episode_id does not match lifecycle/epoch")


def build_profile_data_record(
    *,
    record_type: ProfileRecordType,
    process_uuid: str,
    record_seq: int,
    timestamp_ns: int,
    clock_domain_id: str,
    config: KVRecoveryProfileConfig,
    fields: Mapping[str, object],
) -> tuple[dict[str, object], ProfileRecordRef]:
    if record_type not in {
        "block_set_chunk",
        "wait_set_chunk",
        "transfer_event",
        "recovery_event",
    }:
        raise ValueError("record_type is not in the profile data roster")
    process_uuid = _require_hex(process_uuid, 32, "process_uuid")
    record_seq = _require_uint(record_seq, _UINT64_MAX, "record_seq")
    timestamp_ns = _require_uint(timestamp_ns, _UINT64_MAX, "timestamp_ns")
    record_id = f"{process_uuid}:k:{record_seq}"
    required = (
        _WAIT_FIELDS
        if record_type == "wait_set_chunk"
        else _REQUEST_FIELDS
        | {
            "block_set_chunk": _BLOCK_FIELDS,
            "transfer_event": _TRANSFER_FIELDS,
            "recovery_event": _RECOVERY_FIELDS,
        }[record_type]
    )
    _require_exact_fields(fields, required, record_type)
    if record_type != "wait_set_chunk":
        _validate_request_fields(fields)
    if record_type == "block_set_chunk":
        _validate_block_fields(fields)
    elif record_type == "wait_set_chunk":
        _validate_wait_fields(fields, process_uuid)
    elif record_type == "transfer_event":
        _validate_transfer_fields(fields, process_uuid)
    else:
        _validate_recovery_fields(fields)
    record: dict[str, object] = {
        "schema": config.profile_id,
        "record_type": record_type,
        "process_uuid": process_uuid,
        "record_seq": record_seq,
        "record_id": record_id,
        "run_id": config.run_id,
        "timestamp_ns": timestamp_ns,
        "clock_domain_id": _require_hex(clock_domain_id, 32, "clock_domain_id"),
        "profile_id": config.profile_id,
        **fields,
    }
    _bounded_line(record)
    return record, ProfileRecordRef(
        record_type=record_type,
        record_seq=record_seq,
        record_id=record_id,
        timestamp_ns=timestamp_ns,
        record=record,
    )


def _validate_chunk(index: object, count: object, total: object, field: str) -> None:
    index = _require_uint(index, _UINT32_MAX, "chunk_index")
    count = _require_uint(count, _UINT32_MAX, "chunk_count")
    total = _require_uint(total, _UINT32_MAX, field)
    if count < 1 or index >= count or total < 1:
        raise ValueError("chunk identity/count is invalid")


def _validate_block_fields(fields: Mapping[str, object]) -> None:
    _require_hex(fields["block_set_id"], 64, "block_set_id")
    _validate_chunk(
        fields["chunk_index"],
        fields["chunk_count"],
        fields["total_block_count"],
        "total_block_count",
    )
    total = fields["total_block_count"]
    assert isinstance(total, int)
    if total > MAX_LOGICAL_BLOCKS_PER_BLOCK_SET:
        raise ValueError("block set exceeds its frozen bound")
    blocks = fields["blocks"]
    if not isinstance(blocks, (tuple, list)) or not 1 <= len(blocks) <= 64:
        raise ValueError("blocks must be a nonempty bounded array")
    previous: tuple[int, int] | None = None
    logical_ids: set[str] = set()
    for block in blocks:
        if not isinstance(block, Mapping) or set(block) != {
            "group_index",
            "logical_ordinal",
            "logical_block_id",
        }:
            raise ValueError("block row differs from the closed roster")
        group = _require_uint(block["group_index"], _UINT32_MAX, "group_index")
        ordinal = _require_uint(
            block["logical_ordinal"], _UINT64_MAX, "logical_ordinal"
        )
        logical_id = _require_hex(block["logical_block_id"], 32, "logical_block_id")
        coordinate = (group, ordinal)
        if previous is not None and coordinate <= previous:
            raise ValueError("block rows are not strictly canonical")
        if logical_id in logical_ids:
            raise ValueError("logical_block_id is duplicated")
        previous = coordinate
        logical_ids.add(logical_id)


def _validate_wait_fields(fields: Mapping[str, object], process_uuid: str) -> None:
    if fields["operation"] != "transfer_wait":
        raise ValueError("wait operation must be transfer_wait")
    _require_hex(fields["wait_set_id"], 64, "wait_set_id")
    _validate_chunk(
        fields["chunk_index"],
        fields["chunk_count"],
        fields["total_transfer_count"],
        "total_transfer_count",
    )
    total = fields["total_transfer_count"]
    assert isinstance(total, int)
    if total > MAX_TRANSFER_IDS_PER_WAIT_SET:
        raise ValueError("wait set exceeds its frozen bound")
    transfer_ids = fields["transfer_ids"]
    if not isinstance(transfer_ids, (tuple, list)) or not 1 <= len(transfer_ids) <= 64:
        raise ValueError("transfer_ids must be a nonempty bounded array")
    previous: str | None = None
    for transfer_id in transfer_ids:
        if not isinstance(transfer_id, str) or not _TRANSFER_ID.fullmatch(transfer_id):
            raise ValueError("wait member is not a canonical transfer_id")
        if not transfer_id.startswith(f"{process_uuid}:t:"):
            raise ValueError("wait member belongs to another process")
        if previous is not None and transfer_id <= previous:
            raise ValueError("wait members are not strictly sorted and unique")
        previous = transfer_id


def _validate_transfer_fields(fields: Mapping[str, object], process_uuid: str) -> None:
    transfer_id = fields["transfer_id"]
    if not isinstance(transfer_id, str) or not _TRANSFER_ID.fullmatch(transfer_id):
        raise ValueError("transfer_id is not canonical")
    if not transfer_id.startswith(f"{process_uuid}:t:"):
        raise ValueError("transfer_id belongs to another process")
    _require_uint(fields["connector_job_id"], _UINT64_MAX, "connector_job_id")
    if fields["rank"] != 0 or fields["world_size"] != 1:
        raise ValueError("profile v1alpha1 transfer requires rank 0/world 1")
    operation = fields["operation"]
    if operation not in {"d2h_preserve", "h2d_restore"}:
        raise ValueError("transfer operation is not in the closed roster")
    expected = {
        "d2h_preserve": ("d2h", "device_hbm", "host_cpu"),
        "h2d_restore": ("h2d", "host_cpu", "device_hbm"),
    }[operation]
    if (fields["direction"], fields["src_medium"], fields["dst_medium"]) != expected:
        raise ValueError("transfer direction/media do not match the operation")
    _require_hex(fields["block_set_id"], 64, "block_set_id")
    phase = fields["transfer_phase"]
    if phase == "submit":
        if any(
            fields[name] is not None
            for name in ("bytes_moved", "device_duration_ns", "success", "failure_code")
        ):
            raise ValueError("submit fields must retain their null wire values")
    elif phase == "done":
        success = fields["success"]
        if type(success) is not bool:
            raise ValueError("done success must be Boolean")
        if success:
            bytes_moved = _require_uint(
                fields["bytes_moved"], _UINT64_MAX, "bytes_moved"
            )
            if bytes_moved < 1 or fields["failure_code"] is not None:
                raise ValueError(
                    "successful done requires positive bytes and no failure"
                )
        else:
            if fields["failure_code"] not in {
                "submit_rejected",
                "transfer_failed",
                "cancelled",
                "timeout",
                "size_unavailable",
                "unclassified",
            }:
                raise ValueError("failed done requires a closed failure_code")
        duration = fields["device_duration_ns"]
        if duration is not None and (
            not _is_uint(duration, _UINT64_MAX) or duration < 1
        ):
            raise ValueError("device_duration_ns must be null or positive uint64")
    else:
        raise ValueError("transfer_phase is not submit|done")


def _validate_recovery_fields(fields: Mapping[str, object]) -> None:
    stage = fields["stage"]
    if stage not in {
        "preempt",
        "restore_start",
        "restore_done",
        "scheduler_wakeup",
        "requeue",
        "admission",
        "first_prefill_or_decode",
    }:
        raise ValueError("recovery stage is not in the seven-stage roster")
    occurrence = _require_uint(fields["occurrence"], _UINT32_MAX, "occurrence")
    if stage == "requeue":
        if occurrence >= MAX_REQUEUE_OBSERVATIONS_PER_EPISODE:
            raise ValueError("requeue occurrence exceeds its frozen bound")
    elif occurrence != 0:
        raise ValueError("unique recovery stages require occurrence=0")
    base_event_id = _require_nullable_event_id(fields["base_event_id"], "base_event_id")
    admission_id = _require_nullable_event_id(
        fields["base_admission_started_event_id"],
        "base_admission_started_event_id",
    )
    predecessor = _require_nullable_profile_record_id(
        fields["from_profile_event_id"], "from_profile_event_id"
    )
    if stage in {
        "preempt",
        "restore_start",
        "restore_done",
        "admission",
        "first_prefill_or_decode",
    }:
        if base_event_id is None:
            raise ValueError("stage requires an exact base_event_id")
    elif base_event_id is not None:
        raise ValueError("profile-only stage forbids base_event_id")
    if stage == "preempt":
        if predecessor is not None:
            raise ValueError("preempt starts the profile predecessor chain")
    elif predecessor is None:
        raise ValueError("non-preempt stage requires from_profile_event_id")
    if (stage == "admission") != (admission_id is not None):
        raise ValueError("base admission ID is required only for admission")
    transfer_id = fields["transfer_id"]
    block_set_id = fields["block_set_id"]
    bytes_moved = fields["bytes_moved"]
    if stage == "preempt":
        if any(value is not None for value in (transfer_id, block_set_id, bytes_moved)):
            raise ValueError("preempt precedes transfer identity")
    else:
        if not isinstance(transfer_id, str) or not _TRANSFER_ID.fullmatch(transfer_id):
            raise ValueError("recovery stage requires a canonical transfer_id")
        _require_hex(block_set_id, 64, "block_set_id")
        if stage == "restore_start":
            if bytes_moved is not None:
                raise ValueError("restore_start bytes_moved must be null")
        else:
            moved = _require_uint(bytes_moved, _UINT64_MAX, "bytes_moved")
            if moved < 1:
                raise ValueError("post-restore stage requires positive bytes_moved")
    reason = fields["requeue_reason"]
    if stage == "requeue":
        if reason not in {
            "lora_capacity",
            "prefill_throttled",
            "token_budget",
            "encoder_budget",
            "block_capacity",
            "unclassified",
        }:
            raise ValueError("requeue_reason is not in the closed roster")
    elif reason is not None:
        raise ValueError("requeue_reason is required only for requeue")
    compute_kind = fields["compute_kind"]
    child_kind = fields["child_observation_kind"]
    association_kind = fields["base_association_kind"]
    association_evidence = fields["base_association_evidence"]
    if stage == "first_prefill_or_decode":
        if (
            compute_kind not in {"prefill", "decode"}
            or child_kind != "worker_model_forward_entry"
            or association_kind != "phase_child_observation"
            or association_evidence != "instrumented_execution_context"
        ):
            raise ValueError("first compute child association is incomplete")
    elif any(
        value is not None
        for value in (
            compute_kind,
            child_kind,
            association_kind,
            association_evidence,
        )
    ):
        raise ValueError("compute child fields are required only at first compute")
    for name in ("request_status_before", "request_status_after"):
        value = fields[name]
        if value is not None:
            _require_ascii(value, name, maximum=64)


def build_profile_loss_interval_record(
    *,
    process_uuid: str,
    config: KVRecoveryProfileConfig,
    loss_interval_seq: int,
    reason: LossReason,
    first_dropped_record_seq: int,
    last_dropped_record_seq: int,
    counts: Mapping[ProfileRecordType, int],
    first_observed_timestamp_ns: int,
    last_observed_timestamp_ns: int,
) -> dict[str, object]:
    if reason not in {
        "serialization_failure",
        "queue_overflow",
        "writer_failure",
        "close_timeout",
    }:
        raise ValueError("profile loss reason is outside the closed roster")
    expected_keys = {
        "block_set_chunk",
        "wait_set_chunk",
        "transfer_event",
        "recovery_event",
    }
    if set(counts) != expected_keys:
        raise ValueError("profile loss category roster differs")
    validated_counts = {
        name: _require_uint(counts[name], _UINT64_MAX, f"{name}_count")
        for name in sorted(expected_keys)
    }
    first = _require_uint(
        first_dropped_record_seq, _UINT64_MAX, "first_dropped_record_seq"
    )
    last = _require_uint(
        last_dropped_record_seq, _UINT64_MAX, "last_dropped_record_seq"
    )
    dropped = last - first + 1
    if last < first or sum(validated_counts.values()) != dropped:
        raise ValueError("profile loss interval counts do not reconcile")
    process_uuid = _require_hex(process_uuid, 32, "process_uuid")
    loss_interval_seq = _require_uint(
        loss_interval_seq, _UINT64_MAX, "loss_interval_seq"
    )
    record = {
        "schema": config.profile_id,
        "record_type": "loss_interval",
        "process_uuid": process_uuid,
        "profile_id": config.profile_id,
        "loss_interval_seq": loss_interval_seq,
        "loss_interval_id": f"{process_uuid}:l:{loss_interval_seq}",
        "reason": reason,
        "first_dropped_record_seq": first,
        "last_dropped_record_seq": last,
        "dropped_count": dropped,
        "block_set_chunk_count": validated_counts["block_set_chunk"],
        "wait_set_chunk_count": validated_counts["wait_set_chunk"],
        "transfer_event_count": validated_counts["transfer_event"],
        "recovery_event_count": validated_counts["recovery_event"],
        "first_observed_timestamp_ns": _require_uint(
            first_observed_timestamp_ns,
            _UINT64_MAX,
            "first_observed_timestamp_ns",
        ),
        "last_observed_timestamp_ns": _require_uint(
            last_observed_timestamp_ns,
            _UINT64_MAX,
            "last_observed_timestamp_ns",
        ),
    }
    _bounded_line(record)
    return record


def build_profile_summary_record(
    *,
    process_uuid: str,
    config: KVRecoveryProfileConfig,
    ended_timestamp_ns: int,
    attempted_data_count: int,
    written_counts: Mapping[ProfileRecordType, int],
    written_loss_interval_count: int,
    dropped_data_count: int,
    dropped_control_count: int,
    writer_failure_count: int,
    close_outcome: str,
    content_sha256: str,
) -> dict[str, object]:
    expected_keys = {
        "block_set_chunk",
        "wait_set_chunk",
        "transfer_event",
        "recovery_event",
    }
    if set(written_counts) != expected_keys:
        raise ValueError("profile summary category roster differs")
    attempted = _require_uint(attempted_data_count, _UINT64_MAX, "attempted_data_count")
    dropped = _require_uint(dropped_data_count, _UINT64_MAX, "dropped_data_count")
    validated_counts = {
        name: _require_uint(written_counts[name], _UINT64_MAX, f"written_{name}_count")
        for name in sorted(expected_keys)
    }
    if attempted != sum(validated_counts.values()) + dropped:
        raise ValueError("profile summary ledger does not reconcile")
    if close_outcome not in {"drained", "timeout", "writer_failure"}:
        raise ValueError("profile close_outcome is outside the closed roster")
    record = {
        "schema": config.profile_id,
        "record_type": "profile_summary",
        "process_uuid": _require_hex(process_uuid, 32, "process_uuid"),
        "profile_id": config.profile_id,
        "ended_timestamp_ns": _require_uint(
            ended_timestamp_ns, _UINT64_MAX, "ended_timestamp_ns"
        ),
        "attempted_data_count": attempted,
        "written_block_set_chunk_count": validated_counts["block_set_chunk"],
        "written_wait_set_chunk_count": validated_counts["wait_set_chunk"],
        "written_transfer_event_count": validated_counts["transfer_event"],
        "written_recovery_event_count": validated_counts["recovery_event"],
        "written_loss_interval_count": _require_uint(
            written_loss_interval_count,
            _UINT64_MAX,
            "written_loss_interval_count",
        ),
        "dropped_data_count": dropped,
        "dropped_control_count": _require_uint(
            dropped_control_count, _UINT64_MAX, "dropped_control_count"
        ),
        "first_data_record_seq": 0 if attempted else None,
        "last_data_record_seq": attempted - 1 if attempted else None,
        "writer_failure_count": _require_uint(
            writer_failure_count, _UINT64_MAX, "writer_failure_count"
        ),
        "close_outcome": close_outcome,
        "content_sha256": _require_hex(content_sha256, 64, "content_sha256"),
    }
    _bounded_line(record)
    return record


__all__ = [
    "COMMUNICATION_MODE",
    "MAX_BLOCK_ROWS_PER_CHUNK",
    "MAX_PROFILE_DATA_RECORDS",
    "MAX_WAIT_SET_ROWS_PER_CHUNK",
    "PROFILE_ID",
    "PROFILE_LIMITS",
    "KVRecoveryProfileConfig",
    "LossReason",
    "ProfileLossInterval",
    "ProfileRecord",
    "ProfileRecordRef",
    "ProfileRecordType",
    "build_profile_data_record",
    "build_profile_loss_interval_record",
    "build_profile_start_record",
    "build_profile_summary_record",
    "profile_record_line",
]
