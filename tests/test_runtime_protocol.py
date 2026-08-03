from __future__ import annotations

import hashlib
import json

import pytest

from vllm_request_lifecycle_profiler.runtime_protocol import (
    EdgeDraft,
    EventDraft,
    ProtocolValidationError,
    RuntimeProvenance,
    build_edge_record,
    build_event_record,
    build_loss_interval_record,
    canonical_json_line,
    derive_clock_domain_id,
)

PROCESS_UUID = "1" * 32
TRACE_ID = "2" * 32
CLOCK_DOMAIN_ID = "3" * 32
PARENT_COMMIT = "84261a2458e1f961b0279b70780ca9497bad3f2e"
RUNTIME_COMMIT = "f229ba7cad21a4dba58681af6738a9fd947388e2"
DEVICE_COMMIT = "cafad89a5e103f31ea517c1edb56130578c3cd56"
UINT64_MAX = 2**64 - 1
UINT32_MAX = 2**32 - 1


def _received(**metadata: object) -> EventDraft:
    values: dict[str, object] = {
        "entry_mode": "llm_engine",
        "input_mode": "pretokenized",
        "response_mode": "none",
        "sampling_n": 1,
        "prompt_count": 1,
        "model_mode": "decoder_only",
        "kv_cache_mode": "local_homogeneous",
        "cache_block_size_tokens": 16,
        "frontend_stop_mode": "none",
        "communication_mode": "none",
    }
    values.update(metadata)
    return EventDraft(
        trace_id=TRACE_ID,
        lifecycle_id=f"{TRACE_ID}:r",
        parent_lifecycle_id=None,
        scope="root_request",
        component="frontend",
        event_name="received",
        metadata=values,
    )


def test_canonical_json_line_is_sorted_compact_and_lf_terminated() -> None:
    encoded = canonical_json_line({"z": 1, "a": {"z": 2, "a": 3}})

    assert encoded == b'{"a":{"a":3,"z":2},"z":1}\n'
    assert json.loads(encoded) == {"a": {"a": 3, "z": 2}, "z": 1}


def test_canonical_json_line_rejects_nan_and_oversize() -> None:
    with pytest.raises(ProtocolValidationError, match="deterministic JSON"):
        canonical_json_line({"value": float("nan")})
    with pytest.raises(ProtocolValidationError, match="4096"):
        canonical_json_line({"value": "x" * 4096})


def test_clock_domain_id_matches_frozen_sha256_construction() -> None:
    boot_id = "12345678-1234-4abc-8def-1234567890ab"
    expected = (
        hashlib.sha256(boot_id.encode("ascii") + b"\x00CLOCK_MONOTONIC")
        .digest()[:16]
        .hex()
    )

    assert derive_clock_domain_id(boot_id + "\n") == expected
    with pytest.raises(ProtocolValidationError, match="canonical"):
        derive_clock_domain_id(boot_id + "\n\n")
    with pytest.raises(ProtocolValidationError, match="canonical"):
        derive_clock_domain_id(boot_id.upper())


def test_runtime_provenance_requires_exact_lowercase_git_ids() -> None:
    assert (
        RuntimeProvenance(
            PARENT_COMMIT, RUNTIME_COMMIT, DEVICE_COMMIT
        ).runtime_core_commit
        == RUNTIME_COMMIT
    )
    with pytest.raises(ProtocolValidationError, match="40 lowercase"):
        RuntimeProvenance("bad", RUNTIME_COMMIT, DEVICE_COMMIT)


@pytest.mark.parametrize(
    ("metadata", "message"),
    [
        ({"bad_float": 0.5}, "value type"),
        ({"prompt_text": "secret"}, "forbidden payload"),
        ({"BadKey": 1}, "key"),
        ({"long_value": "x" * 129}, "128"),
        ({f"k{index}": "x" * 120 for index in range(12)}, "1024"),
    ],
)
def test_event_metadata_is_bounded_and_private(
    metadata: dict[str, object], message: str
) -> None:
    with pytest.raises(ProtocolValidationError, match=message):
        build_event_record(
            _received(**metadata),
            process_uuid=PROCESS_UUID,
            clock_domain_id=CLOCK_DOMAIN_ID,
            record_seq=0,
            default_timestamp_ns=1,
        )


def test_event_identity_component_and_span_rules_are_strict() -> None:
    span_id = f"{PROCESS_UUID}:s:0"
    valid = EventDraft(
        trace_id=TRACE_ID,
        lifecycle_id=f"{TRACE_ID}:r",
        parent_lifecycle_id=None,
        scope="root_request",
        component="frontend",
        event_name="render_started",
        start_span_id=span_id,
    )
    record, reference = build_event_record(
        valid,
        process_uuid=PROCESS_UUID,
        clock_domain_id=CLOCK_DOMAIN_ID,
        record_seq=7,
        default_timestamp_ns=11,
    )

    assert record["event_id"] == f"{PROCESS_UUID}:e:7"
    assert record["start_span_id"] == span_id
    assert reference.record_seq == 7
    with pytest.raises(ProtocolValidationError, match="ownership"):
        build_event_record(
            EventDraft(
                **{
                    **valid.__dict__,
                    "component": "tokenizer",
                }
            ),
            process_uuid=PROCESS_UUID,
            clock_domain_id=CLOCK_DOMAIN_ID,
            record_seq=8,
            default_timestamp_ns=12,
        )
    with pytest.raises(ProtocolValidationError, match="creator"):
        build_event_record(
            EventDraft(
                **{
                    **valid.__dict__,
                    "start_span_id": f"{'4' * 32}:s:0",
                }
            ),
            process_uuid=PROCESS_UUID,
            clock_domain_id=CLOCK_DOMAIN_ID,
            record_seq=9,
            default_timestamp_ns=13,
        )


def test_end_and_closing_span_id_sequences_are_bounded_uint64() -> None:
    max_span_id = f"{'4' * 32}:s:{UINT64_MAX}"
    overflow_span_id = f"{'4' * 32}:s:{UINT64_MAX + 1}"
    render_done = EventDraft(
        trace_id=TRACE_ID,
        lifecycle_id=f"{TRACE_ID}:r",
        parent_lifecycle_id=None,
        scope="root_request",
        component="frontend",
        event_name="render_done",
        end_span_id=max_span_id,
    )
    record, _ = build_event_record(
        render_done,
        process_uuid=PROCESS_UUID,
        clock_domain_id=CLOCK_DOMAIN_ID,
        record_seq=0,
        default_timestamp_ns=1,
    )
    assert record["end_span_id"] == max_span_id

    with pytest.raises(ProtocolValidationError, match="out of range"):
        build_event_record(
            EventDraft(**{**render_done.__dict__, "end_span_id": overflow_span_id}),
            process_uuid=PROCESS_UUID,
            clock_domain_id=CLOCK_DOMAIN_ID,
            record_seq=1,
            default_timestamp_ns=2,
        )

    abnormal = EventDraft(
        trace_id=TRACE_ID,
        lifecycle_id=f"{TRACE_ID}:r",
        parent_lifecycle_id=None,
        scope="root_request",
        component="frontend",
        event_name="error",
        closing_span_ids=(max_span_id,),
    )
    record, _ = build_event_record(
        abnormal,
        process_uuid=PROCESS_UUID,
        clock_domain_id=CLOCK_DOMAIN_ID,
        record_seq=2,
        default_timestamp_ns=3,
    )
    assert record["closing_span_ids"] == [max_span_id]

    with pytest.raises(ProtocolValidationError, match="out of range"):
        build_event_record(
            EventDraft(
                **{**abnormal.__dict__, "closing_span_ids": (overflow_span_id,)}
            ),
            process_uuid=PROCESS_UUID,
            clock_domain_id=CLOCK_DOMAIN_ID,
            record_seq=3,
            default_timestamp_ns=4,
        )


def test_serialization_started_carries_handoff_id_without_handoff_index() -> None:
    span_id = f"{PROCESS_UUID}:s:0"
    handoff_id = f"{TRACE_ID}:h:{UINT32_MAX}"
    started = EventDraft(
        trace_id=TRACE_ID,
        lifecycle_id=f"{TRACE_ID}:s",
        parent_lifecycle_id=f"{TRACE_ID}:r",
        scope="response",
        component="response",
        event_name="serialization_started",
        start_span_id=span_id,
        handoff_index=None,
        chunk_index=0,
        handoff_id=handoff_id,
    )
    record, _ = build_event_record(
        started,
        process_uuid=PROCESS_UUID,
        clock_domain_id=CLOCK_DOMAIN_ID,
        record_seq=0,
        default_timestamp_ns=1,
    )

    assert record["handoff_id"] == handoff_id
    assert record["handoff_index"] is None
    assert record["chunk_index"] == 0

    with pytest.raises(ProtocolValidationError, match="null handoff_index"):
        build_event_record(
            EventDraft(**{**started.__dict__, "handoff_index": 0}),
            process_uuid=PROCESS_UUID,
            clock_domain_id=CLOCK_DOMAIN_ID,
            record_seq=1,
            default_timestamp_ns=2,
        )
    with pytest.raises(ProtocolValidationError, match="out of range"):
        build_event_record(
            EventDraft(
                **{
                    **started.__dict__,
                    "handoff_id": f"{TRACE_ID}:h:{UINT32_MAX + 1}",
                }
            ),
            process_uuid=PROCESS_UUID,
            clock_domain_id=CLOCK_DOMAIN_ID,
            record_seq=2,
            default_timestamp_ns=3,
        )

    serialization_done = EventDraft(
        trace_id=TRACE_ID,
        lifecycle_id=f"{TRACE_ID}:s",
        parent_lifecycle_id=f"{TRACE_ID}:r",
        scope="response",
        component="response",
        event_name="serialization_done",
        end_span_id=span_id,
        chunk_index=0,
        handoff_id=f"{TRACE_ID}:h:0",
    )
    with pytest.raises(ProtocolValidationError, match="non-handoff"):
        build_event_record(
            serialization_done,
            process_uuid=PROCESS_UUID,
            clock_domain_id=CLOCK_DOMAIN_ID,
            record_seq=3,
            default_timestamp_ns=4,
        )


def test_loss_interval_rejects_uint64_count_sum_overflow() -> None:
    with pytest.raises(ProtocolValidationError, match="dropped_count.*out of range"):
        build_loss_interval_record(
            process_uuid=PROCESS_UUID,
            loss_interval_seq=0,
            reason="serialization_failure",
            first_dropped_record_seq=0,
            last_dropped_record_seq=UINT64_MAX,
            event_count=UINT64_MAX,
            edge_count=1,
            first_observed_timestamp_ns=1,
            last_observed_timestamp_ns=1,
        )


def test_edge_endpoint_sequences_are_bounded_uint64() -> None:
    valid = EdgeDraft(
        trace_id=TRACE_ID,
        from_event_id=f"{PROCESS_UUID}:e:{UINT64_MAX}",
        to_event_id=f"{'4' * 32}:e:0",
        edge_kind="program_order",
        evidence_source="instrumented_execution_context",
    )
    record, _ = build_edge_record(
        valid,
        process_uuid=PROCESS_UUID,
        record_seq=0,
        communication_mode="none",
    )
    assert record["from_event_id"] == valid.from_event_id

    with pytest.raises(ProtocolValidationError, match="out of range"):
        build_edge_record(
            EdgeDraft(
                **{
                    **valid.__dict__,
                    "from_event_id": f"{PROCESS_UUID}:e:{UINT64_MAX + 1}",
                }
            ),
            process_uuid=PROCESS_UUID,
            record_seq=1,
            communication_mode="none",
        )


def test_issue2_edge_is_rejected_while_communication_mode_is_none() -> None:
    draft = EdgeDraft(
        trace_id=TRACE_ID,
        from_event_id=f"{PROCESS_UUID}:e:0",
        to_event_id=f"{PROCESS_UUID}:e:1",
        edge_kind="data_dependency",
        evidence_source="issue2:v1:collective",
    )

    with pytest.raises(ProtocolValidationError, match="forbidden"):
        build_edge_record(
            draft,
            process_uuid=PROCESS_UUID,
            record_seq=2,
            communication_mode="none",
        )
