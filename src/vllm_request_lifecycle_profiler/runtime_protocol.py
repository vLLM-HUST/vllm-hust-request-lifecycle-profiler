"""Frozen v1alpha1 runtime-record primitives.

This module owns bounded record construction and deterministic encoding. It
does not perform file or thread I/O; :mod:`runtime_hooks` remains the single
runtime exporter implementation.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

SCHEMA_VERSION = "rlp.trace/v1alpha1"
KV_RECOVERY_COMMUNICATION_MODE = "issue2:kv-recovery-v1alpha1"
KV_RECOVERY_H2D_EVIDENCE = f"{KV_RECOVERY_COMMUNICATION_MODE}:h2d_restore"
PARENT_API_MAJOR = 1
CLOCK_SOURCE = "CLOCK_MONOTONIC"

DATA_CAPACITY_RECORDS = 4096
RESERVED_CAPACITY_RECORDS = 64
MAX_RECORD_BYTES = 4096
MAX_QUEUED_BYTES = 17_039_360
MAX_BATCH_RECORDS = 128
MAX_BATCH_BYTES = 262_144
WRITE_INTERVAL_MS = 100
CLOSE_TIMEOUT_MS = 2000
MAX_METADATA_BYTES = 1024

EXPORTER_LIMITS: dict[str, int | str] = {
    "data_capacity_records": DATA_CAPACITY_RECORDS,
    "reserved_capacity_records": RESERVED_CAPACITY_RECORDS,
    "max_record_bytes": MAX_RECORD_BYTES,
    "max_queued_bytes": MAX_QUEUED_BYTES,
    "max_batch_records": MAX_BATCH_RECORDS,
    "max_batch_bytes": MAX_BATCH_BYTES,
    "write_interval_ms": WRITE_INTERVAL_MS,
    "close_timeout_ms": CLOSE_TIMEOUT_MS,
    "shard_ownership": "one_process_one_append_only_shard",
}

MetadataValue = None | bool | int | str

_UINT32_MAX = 2**32 - 1
_UINT64_MAX = 2**64 - 1
_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_METADATA_KEY = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
_EVENT_ID = re.compile(r"^[0-9a-f]{32}:e:(0|[1-9][0-9]{0,19})$")
_SPAN_ID = re.compile(r"^[0-9a-f]{32}:s:(0|[1-9][0-9]{0,19})$")
_HANDOFF_ID = re.compile(r"^[0-9a-f]{32}:h:(0|[1-9][0-9]{0,19})$")
_ISSUE_2_EVIDENCE = re.compile(r"^issue2:[a-z0-9_.-]+:[a-z0-9_.-]+$")
_TRANSFER_ID = re.compile(r"^[0-9a-f]{32}:t:(0|[1-9][0-9]{0,19})$")

SCOPES = frozenset({"root_request", "engine_sample", "response"})
COMPONENTS = frozenset(
    {
        "frontend",
        "tokenizer",
        "engine_client",
        "engine_core",
        "output_processor",
        "response",
        "transport",
        "external_evidence",
    }
)
EDGE_KINDS = frozenset(
    {
        "program_order",
        "data_dependency",
        "submission",
        "parent_child",
        "transport_handoff",
        "correlated_same_clock_domain",
    }
)
EVIDENCE_SOURCES = frozenset(
    {
        "instrumented_execution_context",
        "engine_submission",
        "lifecycle_creation",
        "engine_output_handoff",
        "engine_abort_handoff",
        "transport_send_await",
    }
)
LOSS_REASONS = frozenset(
    {
        "serialization_failure",
        "queue_overflow",
        "writer_failure",
        "close_timeout",
    }
)
UNSUPPORTED_REASONS = frozenset(
    {
        "parallel_sampling",
        "beam_search",
        "pooling",
        "streaming_input",
        "cross_host",
        "response_boundary_uninstrumented",
        "communication_subtype_unfrozen",
        "zero_compute_prefix_hit",
        "kv_connector_enabled",
        "heterogeneous_kv_cache",
        "frontend_stop_string",
        "multimodal_input",
        "prompt_embeds",
        "encoder_decoder_model",
        "batched_prompts",
    }
)

_FORBIDDEN_METADATA_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "client_ip",
        "generated_text",
        "input_text",
        "messages",
        "output_text",
        "prompt",
        "prompt_text",
        "raw_model_output",
        "raw_output",
        "request_body",
        "token",
        "token_ids",
    }
)

_COMPONENT_BY_SCOPE_EVENT: dict[tuple[str, str], str] = {}


def _register(scope: str, component: str, *events: str) -> None:
    for event in events:
        _COMPONENT_BY_SCOPE_EVENT[(scope, event)] = component


_register(
    "root_request",
    "frontend",
    "received",
    "render_started",
    "render_done",
    "request_done",
    "cancelled",
    "error",
    "unsupported_mode",
    "cleanup_started",
    "cleanup_done",
)
_register(
    "root_request",
    "tokenizer",
    "tokenization_started",
    "tokenization_done",
)
_register("root_request", "engine_client", "submitted")
_register("root_request", "output_processor", "output_ready")
_register(
    "engine_sample",
    "engine_core",
    "requeued",
    "admission_started",
    "scheduled",
    "resumed",
    "prefill_started",
    "prefill_done",
    "decode_started",
    "decode_done",
    "preempted",
    "generation_done",
    "aborted",
    "cancelled",
    "error",
    "cleanup_started",
    "cleanup_done",
)
_register("engine_sample", "engine_client", "queued")
_register(
    "engine_sample",
    "output_processor",
    "first_token",
    "output_batch_ready",
)
_register(
    "engine_sample",
    "external_evidence",
    "communication_started",
    "communication_done",
)
_register(
    "response",
    "response",
    "serialization_started",
    "serialization_done",
    "cancelled",
    "error",
    "cleanup_started",
    "cleanup_done",
)
_register(
    "response",
    "transport",
    "delivery_started",
    "delivery_done",
    "stream_done",
)

EVENT_NAMES = frozenset(event for _, event in _COMPONENT_BY_SCOPE_EVENT)
ABNORMAL_TERMINALS = frozenset({"aborted", "cancelled", "error"})
TERMINAL_EVENTS = frozenset(
    {"request_done", "generation_done", "stream_done", *ABNORMAL_TERMINALS}
)
SPAN_START_EVENTS = frozenset(
    {
        "render_started",
        "tokenization_started",
        "queued",
        "requeued",
        "admission_started",
        "prefill_started",
        "decode_started",
        "communication_started",
        "serialization_started",
        "delivery_started",
        "cleanup_started",
    }
)
SPAN_END_EVENTS = frozenset(
    {
        "render_done",
        "tokenization_done",
        "admission_started",
        "scheduled",
        "resumed",
        "prefill_done",
        "decode_done",
        "communication_done",
        "serialization_done",
        "delivery_done",
        "stream_done",
        "cleanup_done",
        "preempted",
    }
)


class ProtocolValidationError(ValueError):
    """A draft cannot be represented by the frozen wire contract."""


@dataclass(frozen=True)
class RuntimeProvenance:
    profiler_parent_commit: str
    runtime_core_commit: str
    device_plugin_commit: str

    def __post_init__(self) -> None:
        for field_name, value in (
            ("profiler_parent_commit", self.profiler_parent_commit),
            ("runtime_core_commit", self.runtime_core_commit),
            ("device_plugin_commit", self.device_plugin_commit),
        ):
            if not isinstance(value, str) or not _HEX40.fullmatch(value):
                raise ProtocolValidationError(
                    f"{field_name} must be 40 lowercase hexadecimal characters"
                )


@dataclass(frozen=True)
class EventDraft:
    trace_id: str
    lifecycle_id: str
    parent_lifecycle_id: str | None
    scope: str
    component: str
    event_name: str
    timestamp_ns: int | None = None
    preemption_epoch: int | None = None
    start_span_id: str | None = None
    end_span_id: str | None = None
    closing_span_ids: tuple[str, ...] = ()
    sample_index: int | None = None
    handoff_index: int | None = None
    chunk_index: int | None = None
    handoff_id: str | None = None
    metadata: Mapping[str, MetadataValue] | None = None


@dataclass(frozen=True)
class EdgeDraft:
    trace_id: str
    from_event_id: str
    to_event_id: str
    edge_kind: str
    evidence_source: str


@dataclass(frozen=True)
class RecordRef:
    record_id: str
    record_seq: int


def new_trace_id() -> str:
    return secrets.token_hex(16)


def new_process_uuid() -> str:
    return uuid.uuid4().hex


def derive_clock_domain_id(boot_id_text: str) -> str:
    if not isinstance(boot_id_text, str):
        raise ProtocolValidationError("boot ID must be text")
    canonical = boot_id_text.removesuffix("\n")
    if not re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        canonical,
    ):
        raise ProtocolValidationError("boot ID is not a canonical lowercase UUID")
    if str(uuid.UUID(canonical)) != canonical:
        raise ProtocolValidationError("boot ID is not canonical")
    digest = hashlib.sha256(
        canonical.encode("ascii") + b"\x00" + CLOCK_SOURCE.encode("ascii")
    ).digest()
    return digest[:16].hex()


def read_clock_domain_id(
    boot_id_path: Path = Path("/proc/sys/kernel/random/boot_id"),
) -> str:
    return derive_clock_domain_id(boot_id_path.read_text(encoding="ascii"))


def canonical_json_line(record: Mapping[str, object]) -> bytes:
    try:
        rendered = json.dumps(
            dict(record),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ProtocolValidationError("record is not deterministic JSON") from exc
    encoded = rendered.encode("utf-8") + b"\n"
    if len(encoded) > MAX_RECORD_BYTES:
        raise ProtocolValidationError("encoded record exceeds 4096 bytes")
    return encoded


def build_process_start_record(
    *,
    process_uuid: str,
    pid: int,
    started_timestamp_ns: int,
    clock_domain_id: str,
    provenance: RuntimeProvenance,
) -> dict[str, object]:
    _require_hex32("process_uuid", process_uuid)
    _require_uint("pid", pid, _UINT32_MAX)
    _require_uint("started_timestamp_ns", started_timestamp_ns, _UINT64_MAX)
    _require_hex32("clock_domain_id", clock_domain_id)
    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": "process_start",
        "process_uuid": process_uuid,
        "pid": pid,
        "started_timestamp_ns": started_timestamp_ns,
        "clock_source": CLOCK_SOURCE,
        "clock_domain_id": clock_domain_id,
        "profiler_parent_commit": provenance.profiler_parent_commit,
        "runtime_core_commit": provenance.runtime_core_commit,
        "device_plugin_commit": provenance.device_plugin_commit,
        "parent_api_major": PARENT_API_MAJOR,
        "limits": dict(EXPORTER_LIMITS),
    }


def build_event_record(
    draft: EventDraft,
    *,
    process_uuid: str,
    clock_domain_id: str,
    record_seq: int,
    default_timestamp_ns: int,
    communication_mode: str = "none",
) -> tuple[dict[str, object], RecordRef]:
    _require_hex32("process_uuid", process_uuid)
    _require_hex32("clock_domain_id", clock_domain_id)
    _require_uint("record_seq", record_seq, _UINT64_MAX)
    timestamp_ns = (
        default_timestamp_ns if draft.timestamp_ns is None else draft.timestamp_ns
    )
    _validate_event_draft(
        draft,
        process_uuid,
        clock_domain_id,
        timestamp_ns,
        communication_mode,
    )
    event_id = f"{process_uuid}:e:{record_seq}"
    record = {
        "schema_version": SCHEMA_VERSION,
        "record_type": "event",
        "process_uuid": process_uuid,
        "record_seq": record_seq,
        "event_id": event_id,
        "trace_id": draft.trace_id,
        "lifecycle_id": draft.lifecycle_id,
        "parent_lifecycle_id": draft.parent_lifecycle_id,
        "scope": draft.scope,
        "component": draft.component,
        "event_name": draft.event_name,
        "timestamp_ns": timestamp_ns,
        "clock_domain_id": clock_domain_id,
        "preemption_epoch": draft.preemption_epoch,
        "start_span_id": draft.start_span_id,
        "end_span_id": draft.end_span_id,
        "closing_span_ids": list(draft.closing_span_ids),
        "sample_index": draft.sample_index,
        "handoff_index": draft.handoff_index,
        "chunk_index": draft.chunk_index,
        "handoff_id": draft.handoff_id,
        "metadata": dict(draft.metadata or {}),
    }
    return record, RecordRef(event_id, record_seq)


def build_edge_record(
    draft: EdgeDraft,
    *,
    process_uuid: str,
    record_seq: int,
    communication_mode: str,
) -> tuple[dict[str, object], RecordRef]:
    if communication_mode not in {"none", KV_RECOVERY_COMMUNICATION_MODE}:
        raise ProtocolValidationError("communication_mode is not implemented")
    _require_hex32("process_uuid", process_uuid)
    _require_hex32("trace_id", draft.trace_id)
    _require_uint("record_seq", record_seq, _UINT64_MAX)
    for field_name, value in (
        ("from_event_id", draft.from_event_id),
        ("to_event_id", draft.to_event_id),
    ):
        _validate_decimal_id(
            field_name,
            value,
            pattern=_EVENT_ID,
            kind="event",
            maximum_bytes=55,
        )
    if draft.from_event_id == draft.to_event_id:
        raise ProtocolValidationError("an edge cannot be a self-edge")
    if draft.edge_kind not in EDGE_KINDS:
        raise ProtocolValidationError("edge_kind is not frozen")
    if draft.evidence_source in EVIDENCE_SOURCES:
        pass
    elif _ISSUE_2_EVIDENCE.fullmatch(draft.evidence_source or ""):
        if (
            communication_mode != KV_RECOVERY_COMMUNICATION_MODE
            or draft.evidence_source != KV_RECOVERY_H2D_EVIDENCE
            or draft.edge_kind != "data_dependency"
        ):
            raise ProtocolValidationError(
                "issue-2 evidence is forbidden outside the frozen recovery mapping"
            )
    else:
        raise ProtocolValidationError("evidence_source is not frozen")
    if len(draft.evidence_source.encode("ascii")) > 64:
        raise ProtocolValidationError("evidence_source exceeds 64 bytes")
    edge_id = f"{process_uuid}:g:{record_seq}"
    record = {
        "schema_version": SCHEMA_VERSION,
        "record_type": "edge",
        "process_uuid": process_uuid,
        "record_seq": record_seq,
        "edge_id": edge_id,
        "trace_id": draft.trace_id,
        "from_event_id": draft.from_event_id,
        "to_event_id": draft.to_event_id,
        "edge_kind": draft.edge_kind,
        "evidence_source": draft.evidence_source,
    }
    return record, RecordRef(edge_id, record_seq)


def build_loss_interval_record(
    *,
    process_uuid: str,
    loss_interval_seq: int,
    reason: str,
    first_dropped_record_seq: int,
    last_dropped_record_seq: int,
    event_count: int,
    edge_count: int,
    first_observed_timestamp_ns: int,
    last_observed_timestamp_ns: int,
) -> dict[str, object]:
    _require_hex32("process_uuid", process_uuid)
    _require_uint("loss_interval_seq", loss_interval_seq, _UINT64_MAX)
    if reason not in LOSS_REASONS:
        raise ProtocolValidationError("loss reason is not frozen")
    for field_name, value in (
        ("first_dropped_record_seq", first_dropped_record_seq),
        ("last_dropped_record_seq", last_dropped_record_seq),
        ("event_count", event_count),
        ("edge_count", edge_count),
        ("first_observed_timestamp_ns", first_observed_timestamp_ns),
        ("last_observed_timestamp_ns", last_observed_timestamp_ns),
    ):
        _require_uint(field_name, value, _UINT64_MAX)
    dropped_count = event_count + edge_count
    _require_uint("dropped_count", dropped_count, _UINT64_MAX)
    if last_dropped_record_seq < first_dropped_record_seq:
        raise ProtocolValidationError("loss interval is inverted")
    if last_observed_timestamp_ns < first_observed_timestamp_ns:
        raise ProtocolValidationError("loss observation timestamps are inverted")
    if dropped_count != last_dropped_record_seq - first_dropped_record_seq + 1:
        raise ProtocolValidationError("loss interval counts do not reconcile")
    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": "loss_interval",
        "process_uuid": process_uuid,
        "loss_interval_seq": loss_interval_seq,
        "loss_interval_id": f"{process_uuid}:l:{loss_interval_seq}",
        "reason": reason,
        "first_dropped_record_seq": first_dropped_record_seq,
        "last_dropped_record_seq": last_dropped_record_seq,
        "dropped_count": dropped_count,
        "event_count": event_count,
        "edge_count": edge_count,
        "first_observed_timestamp_ns": first_observed_timestamp_ns,
        "last_observed_timestamp_ns": last_observed_timestamp_ns,
    }


def build_process_summary_record(
    *,
    process_uuid: str,
    ended_timestamp_ns: int,
    attempted_data_count: int,
    written_event_count: int,
    written_edge_count: int,
    written_loss_interval_count: int,
    dropped_data_count: int,
    dropped_control_count: int,
    writer_failure_count: int,
    close_outcome: str,
    content_sha256: str,
) -> dict[str, object]:
    _require_hex32("process_uuid", process_uuid)
    for field_name, value in (
        ("ended_timestamp_ns", ended_timestamp_ns),
        ("attempted_data_count", attempted_data_count),
        ("written_event_count", written_event_count),
        ("written_edge_count", written_edge_count),
        ("written_loss_interval_count", written_loss_interval_count),
        ("dropped_data_count", dropped_data_count),
        ("dropped_control_count", dropped_control_count),
        ("writer_failure_count", writer_failure_count),
    ):
        _require_uint(field_name, value, _UINT64_MAX)
    if close_outcome not in {"drained", "timeout", "writer_failure"}:
        raise ProtocolValidationError("close_outcome is not frozen")
    if not _HEX64.fullmatch(content_sha256):
        raise ProtocolValidationError("content_sha256 is not lowercase SHA-256")
    if attempted_data_count != (
        written_event_count + written_edge_count + dropped_data_count
    ):
        raise ProtocolValidationError("process summary counts do not reconcile")
    first_seq: int | None = 0 if attempted_data_count else None
    last_seq: int | None = attempted_data_count - 1 if attempted_data_count else None
    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": "process_summary",
        "process_uuid": process_uuid,
        "ended_timestamp_ns": ended_timestamp_ns,
        "attempted_data_count": attempted_data_count,
        "written_event_count": written_event_count,
        "written_edge_count": written_edge_count,
        "written_loss_interval_count": written_loss_interval_count,
        "dropped_data_count": dropped_data_count,
        "dropped_control_count": dropped_control_count,
        "first_data_record_seq": first_seq,
        "last_data_record_seq": last_seq,
        "writer_failure_count": writer_failure_count,
        "close_outcome": close_outcome,
        "content_sha256": content_sha256,
    }


def _validate_event_draft(
    draft: EventDraft,
    process_uuid: str,
    clock_domain_id: str,
    timestamp_ns: int,
    communication_mode: str,
) -> None:
    del clock_domain_id
    _require_hex32("trace_id", draft.trace_id)
    _require_uint("timestamp_ns", timestamp_ns, _UINT64_MAX)
    if draft.scope not in SCOPES:
        raise ProtocolValidationError("scope is not frozen")
    if draft.component not in COMPONENTS:
        raise ProtocolValidationError("component is not frozen")
    if draft.event_name not in EVENT_NAMES:
        raise ProtocolValidationError("event_name is not frozen")
    required_component = _COMPONENT_BY_SCOPE_EVENT.get((draft.scope, draft.event_name))
    if required_component != draft.component:
        raise ProtocolValidationError("component/event/scope ownership mismatch")
    is_communication = draft.event_name.startswith("communication_")
    if is_communication and communication_mode != KV_RECOVERY_COMMUNICATION_MODE:
        raise ProtocolValidationError("communication event mode is not active")
    if not is_communication and communication_mode not in {
        "none",
        KV_RECOVERY_COMMUNICATION_MODE,
    }:
        raise ProtocolValidationError("communication_mode is not implemented")

    _validate_lifecycle_identity(draft)
    _validate_optional_uint("preemption_epoch", draft.preemption_epoch, _UINT32_MAX)
    _validate_optional_uint("sample_index", draft.sample_index, _UINT32_MAX)
    _validate_optional_uint("handoff_index", draft.handoff_index, _UINT32_MAX)
    _validate_optional_uint("chunk_index", draft.chunk_index, _UINT32_MAX)

    if draft.scope == "engine_sample":
        if draft.preemption_epoch is None or draft.sample_index is None:
            raise ProtocolValidationError(
                "engine events require preemption_epoch and sample_index"
            )
    elif draft.preemption_epoch is not None or draft.sample_index is not None:
        raise ProtocolValidationError(
            "non-engine events forbid preemption_epoch and sample_index"
        )

    _validate_span_fields(draft, process_uuid)
    _validate_handoff_and_chunk(draft)
    metadata = _validate_metadata(draft.metadata)
    _validate_event_metadata(draft, metadata)
    if is_communication:
        _validate_kv_recovery_communication_metadata(draft, metadata)


def _validate_kv_recovery_communication_metadata(
    draft: EventDraft,
    metadata: Mapping[str, MetadataValue],
) -> None:
    common_keys = {
        "operation",
        "direction",
        "transfer_id",
        "block_set_id",
        "recovery_profile",
        "communication_mapping",
        "rank",
    }
    expected_keys = common_keys | (
        {"bytes_moved"} if draft.event_name == "communication_done" else set()
    )
    if set(metadata) != expected_keys:
        raise ProtocolValidationError("recovery communication metadata keys differ")
    if metadata.get("operation") != "h2d_restore":
        raise ProtocolValidationError("recovery operation is not h2d_restore")
    if metadata.get("direction") != "h2d":
        raise ProtocolValidationError("recovery direction is not h2d")
    transfer_id = metadata.get("transfer_id")
    if not isinstance(transfer_id, str) or not _TRANSFER_ID.fullmatch(transfer_id):
        raise ProtocolValidationError("recovery transfer_id is invalid")
    block_set_id = metadata.get("block_set_id")
    if not isinstance(block_set_id, str) or not _HEX64.fullmatch(block_set_id):
        raise ProtocolValidationError("recovery metadata block_set_id is invalid")
    if metadata.get("recovery_profile") != "rlp.kv-recovery/v1alpha1":
        raise ProtocolValidationError("recovery profile ID is invalid")
    if metadata.get("communication_mapping") != KV_RECOVERY_COMMUNICATION_MODE:
        raise ProtocolValidationError("communication mapping ID is invalid")
    if metadata.get("rank") != 0:
        raise ProtocolValidationError("recovery communication requires rank zero")
    if (
        draft.event_name == "communication_done"
        and _required_metadata_uint(metadata, "bytes_moved") < 1
    ):
        raise ProtocolValidationError("bytes_moved must be positive")


def _validate_lifecycle_identity(draft: EventDraft) -> None:
    root_id = f"{draft.trace_id}:r"
    if draft.scope == "root_request":
        if draft.lifecycle_id != root_id or draft.parent_lifecycle_id is not None:
            raise ProtocolValidationError("root lifecycle identity is invalid")
    elif draft.scope == "engine_sample":
        if draft.sample_index is None:
            raise ProtocolValidationError("engine lifecycle requires sample_index")
        expected = f"{draft.trace_id}:e:{draft.sample_index}"
        if draft.lifecycle_id != expected or draft.parent_lifecycle_id != root_id:
            raise ProtocolValidationError("engine lifecycle identity is invalid")
    else:
        expected = f"{draft.trace_id}:s"
        if draft.lifecycle_id != expected or draft.parent_lifecycle_id != root_id:
            raise ProtocolValidationError("response lifecycle identity is invalid")
    for value in (draft.lifecycle_id, draft.parent_lifecycle_id):
        if value is not None and len(value.encode("ascii")) > 96:
            raise ProtocolValidationError("lifecycle ID exceeds 96 bytes")


def _validate_span_fields(draft: EventDraft, process_uuid: str) -> None:
    closing = draft.closing_span_ids
    if not isinstance(closing, tuple):
        raise ProtocolValidationError("closing_span_ids must be a tuple")
    if len(closing) > 16 or tuple(sorted(set(closing))) != closing:
        raise ProtocolValidationError(
            "closing_span_ids must be sorted, unique, and bounded"
        )
    for span_id in (*closing, draft.start_span_id, draft.end_span_id):
        if span_id is None:
            continue
        _validate_decimal_id(
            "span_id",
            span_id,
            pattern=_SPAN_ID,
            kind="span",
            maximum_bytes=55,
        )
    if draft.start_span_id is not None and not draft.start_span_id.startswith(
        f"{process_uuid}:s:"
    ):
        raise ProtocolValidationError("span creator must match the start emitter")

    if draft.event_name in ABNORMAL_TERMINALS:
        if draft.start_span_id is not None or draft.end_span_id is not None:
            raise ProtocolValidationError(
                "abnormal terminals use closing_span_ids, not singular span fields"
            )
        return
    if closing:
        raise ProtocolValidationError(
            "non-abnormal events require an empty closing_span_ids array"
        )
    expects_start = draft.event_name in SPAN_START_EVENTS
    expects_end = draft.event_name in SPAN_END_EVENTS
    if (draft.start_span_id is not None) != expects_start:
        raise ProtocolValidationError("start_span_id does not match event boundary")
    if (draft.end_span_id is not None) != expects_end:
        raise ProtocolValidationError("end_span_id does not match event boundary")


def _validate_handoff_and_chunk(draft: EventDraft) -> None:
    indexed_handoff_events = {"output_batch_ready", "output_ready"}
    if draft.event_name in indexed_handoff_events:
        if draft.handoff_index is None:
            raise ProtocolValidationError("handoff event requires handoff_index")
        expected = f"{draft.trace_id}:h:{draft.handoff_index}"
        if draft.handoff_id != expected:
            raise ProtocolValidationError("handoff_id is not canonical")
    elif draft.event_name == "serialization_started":
        if draft.handoff_index is not None:
            raise ProtocolValidationError(
                "serialization_started requires a null handoff_index"
            )
        _validate_decimal_id(
            "handoff_id",
            draft.handoff_id,
            pattern=_HANDOFF_ID,
            kind="handoff",
            maximum_bytes=55,
            maximum_sequence=_UINT32_MAX,
        )
        if not draft.handoff_id.startswith(f"{draft.trace_id}:h:"):
            raise ProtocolValidationError("handoff_id belongs to a different trace")
    elif draft.handoff_index is not None or draft.handoff_id is not None:
        raise ProtocolValidationError("non-handoff event contains handoff fields")

    chunk_events = {
        "serialization_started",
        "serialization_done",
        "delivery_started",
        "delivery_done",
        "stream_done",
    }
    if draft.event_name in chunk_events:
        if draft.scope != "response" or draft.chunk_index is None:
            raise ProtocolValidationError("response chunk event requires chunk_index")
    elif draft.chunk_index is not None:
        raise ProtocolValidationError("non-chunk event contains chunk_index")


def _validate_metadata(
    metadata: Mapping[str, MetadataValue] | None,
) -> dict[str, MetadataValue]:
    if metadata is None:
        return {}
    if not isinstance(metadata, Mapping):
        raise ProtocolValidationError("metadata must be an object")
    result: dict[str, MetadataValue] = {}
    for key, value in metadata.items():
        if not isinstance(key, str) or not _METADATA_KEY.fullmatch(key):
            raise ProtocolValidationError("metadata key is not bounded ASCII")
        if key in _FORBIDDEN_METADATA_KEYS:
            raise ProtocolValidationError("metadata contains forbidden payload data")
        if value is None or isinstance(value, bool):
            pass
        elif isinstance(value, int):
            _require_uint(f"metadata.{key}", value, _UINT64_MAX)
        elif isinstance(value, str):
            if not value.isascii() or any(
                ord(char) < 32 or ord(char) > 126 for char in value
            ):
                raise ProtocolValidationError("metadata string must be printable ASCII")
            if len(value.encode("ascii")) > 128:
                raise ProtocolValidationError("metadata string exceeds 128 bytes")
        else:
            raise ProtocolValidationError("metadata value type is not frozen")
        result[key] = value
    encoded = json.dumps(
        result,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > MAX_METADATA_BYTES:
        raise ProtocolValidationError("metadata exceeds 1024 encoded bytes")
    return result


def _validate_event_metadata(
    draft: EventDraft,
    metadata: Mapping[str, MetadataValue],
) -> None:
    if draft.scope == "root_request" and draft.event_name == "received":
        expected_values: dict[str, object] = {
            "sampling_n": 1,
            "prompt_count": 1,
            "model_mode": "decoder_only",
            "frontend_stop_mode": "none",
            "communication_mode": "none",
        }
        for key, expected in expected_values.items():
            if metadata.get(key) != expected:
                raise ProtocolValidationError(f"received metadata requires {key}")
        if metadata.get("entry_mode") not in {
            "openai_http",
            "async_llm",
            "llm_engine",
        }:
            raise ProtocolValidationError("received entry_mode is unsupported")
        if metadata.get("input_mode") not in {"text", "pretokenized"}:
            raise ProtocolValidationError("received input_mode is unsupported")
        if metadata.get("response_mode") not in {
            "streaming",
            "non_streaming",
            "none",
        }:
            raise ProtocolValidationError("received response_mode is unsupported")
        if (
            metadata["entry_mode"] == "openai_http"
            and metadata["response_mode"] == "none"
        ):
            raise ProtocolValidationError("OpenAI entry requires a response mode")
        if (
            metadata["entry_mode"] != "openai_http"
            and metadata["response_mode"] != "none"
        ):
            raise ProtocolValidationError("direct entry requires response_mode=none")
        if metadata.get("kv_cache_mode") not in {
            "disabled",
            "local_homogeneous",
        }:
            raise ProtocolValidationError("received kv_cache_mode is unsupported")
        cache_block_size = metadata.get("cache_block_size_tokens")
        if metadata["kv_cache_mode"] == "local_homogeneous":
            if (
                isinstance(cache_block_size, bool)
                or not isinstance(cache_block_size, int)
                or cache_block_size < 1
            ):
                raise ProtocolValidationError(
                    "local homogeneous KV requires cache_block_size_tokens"
                )
        elif cache_block_size is not None:
            raise ProtocolValidationError("disabled KV forbids cache_block_size_tokens")
    if (
        draft.event_name == "unsupported_mode"
        and metadata.get("reason_code") not in UNSUPPORTED_REASONS
    ):
        raise ProtocolValidationError("unsupported_mode requires frozen reason_code")
    if draft.event_name in {"cleanup_started", "cleanup_done"}:
        expected = {
            "root_request": "frontend_request",
            "engine_sample": "engine_request",
            "response": "response_stream",
        }[draft.scope]
        if metadata.get("cleanup_component") != expected:
            raise ProtocolValidationError("cleanup_component does not match scope")
    if draft.event_name in {"scheduled", "resumed"}:
        total = _required_metadata_uint(metadata, "prompt_tokens_total")
        cached = _required_metadata_uint(metadata, "prompt_tokens_cached")
        to_compute = _required_metadata_uint(metadata, "prompt_tokens_to_compute")
        if total < 1 or cached >= total or to_compute != total - cached:
            raise ProtocolValidationError("prompt token counters do not reconcile")
    if draft.event_name in {"prefill_done", "preempted"}:
        _required_metadata_uint(metadata, "prompt_tokens_computed")
        if _required_metadata_uint(metadata, "prefill_chunk_count") < 1:
            raise ProtocolValidationError("prefill_chunk_count must be positive")
    if (
        draft.event_name == "generation_done"
        and _required_metadata_uint(metadata, "generated_tokens_total") < 1
    ):
        raise ProtocolValidationError("generated_tokens_total must be positive")


def _required_metadata_uint(metadata: Mapping[str, MetadataValue], key: str) -> int:
    value = metadata.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProtocolValidationError(f"metadata requires uint64 {key}")
    _require_uint(f"metadata.{key}", value, _UINT64_MAX)
    return value


def _require_hex32(field_name: str, value: object) -> None:
    if not isinstance(value, str) or not _HEX32.fullmatch(value):
        raise ProtocolValidationError(
            f"{field_name} must be 32 lowercase hexadecimal characters"
        )


def _require_uint(field_name: str, value: object, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProtocolValidationError(f"{field_name} must be an unsigned integer")
    if value < 0 or value > maximum:
        raise ProtocolValidationError(f"{field_name} is out of range")


def _validate_optional_uint(field_name: str, value: int | None, maximum: int) -> None:
    if value is not None:
        _require_uint(field_name, value, maximum)


def _validate_decimal_id(
    field_name: str,
    value: object,
    *,
    pattern: re.Pattern[str],
    kind: str,
    maximum_bytes: int,
    maximum_sequence: int = _UINT64_MAX,
) -> None:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ProtocolValidationError(f"{field_name} is not a canonical {kind} ID")
    if len(value.encode("ascii")) > maximum_bytes:
        raise ProtocolValidationError(f"{field_name} exceeds {maximum_bytes} bytes")
    decimal_suffix = value.rsplit(":", 1)[1]
    _require_uint(f"{field_name} sequence", int(decimal_suffix), maximum_sequence)
