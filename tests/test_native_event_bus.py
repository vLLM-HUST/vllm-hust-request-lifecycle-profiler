from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from vllm_request_lifecycle_profiler.native_event_bus import (
    NativeEventSnapshot,
    NativeLifecycleEventSink,
)
from vllm_request_lifecycle_profiler.runtime_protocol import (
    build_event_record,
)


@dataclass(frozen=True)
class Finished:
    request_id: str
    session_id: str | None
    prompt_tokens: int
    output_tokens: int
    sequence_tokens: int
    kv_blocks: int
    kv_reclaim_deferred: bool
    finished_reason: str
    ts_monotonic_ns: int = 10


@dataclass(frozen=True)
class Preempted:
    request_id: str
    session_id: str | None
    num_preemptions: int
    kv_blocks: int
    kv_reclaim_deferred: bool
    ts_monotonic_ns: int = 20


@dataclass(frozen=True)
class Reclaimed:
    request_id: str
    session_id: str | None
    kv_blocks: int
    path: str
    ts_monotonic_ns: int = 30


class Hooks:
    enabled = True

    def __init__(self) -> None:
        self.drafts = []

    def emit_event(self, draft):
        self.drafts.append(draft)
        return SimpleNamespace(record_id="record", record_seq=len(self.drafts) - 1)


def make_sink(hooks, evidence):
    return NativeLifecycleEventSink(
        hooks,
        "a" * 32,
        finished_type=Finished,
        preempted_type=Preempted,
        reclaimed_type=Reclaimed,
        evidence_emitter=lambda name, request_id: evidence.append(
            (name, request_id)
        )
        is None,
    )


def test_native_sink_translates_all_current_host_events() -> None:
    hooks = Hooks()
    evidence = []
    sink = make_sink(hooks, evidence)

    sink.emit(Finished("r1", "s1", 5, 2, 7, 3, False, "stop"))
    sink.emit(Preempted("r1", "s1", 1, 3, False))
    sink.emit(Reclaimed("r1", "s1", 3, "immediate"))

    assert [draft.event_name for draft in hooks.drafts] == [
        "request_finished_observed",
        "request_preempted_observed",
        "request_kv_reclaimed_observed",
    ]
    for record_seq, draft in enumerate(hooks.drafts):
        record, _ = build_event_record(
            draft,
            process_uuid="b" * 32,
            clock_domain_id="c" * 32,
            record_seq=record_seq,
            default_timestamp_ns=1,
        )
        assert record["metadata"]["runtime_request_id"] == "r1"
    assert evidence == [
        ("request_finished", "r1"),
        ("request_preempted", "r1"),
        ("request_kv_reclaimed", "r1"),
    ]
    assert sink.snapshot() == NativeEventSnapshot(
        event_count=3,
        finished_count=1,
        preempted_count=1,
        reclaimed_count=1,
    )


def test_disabled_trace_still_observes_without_fabricating_records() -> None:
    hooks = Hooks()
    hooks.enabled = False
    evidence = []
    sink = make_sink(hooks, evidence)

    sink.emit(Reclaimed("r2", None, 1, "deferred"))

    assert hooks.drafts == []
    assert evidence == [("request_kv_reclaimed", "r2")]
    assert sink.snapshot().event_count == 1


def test_unknown_or_malformed_events_fail_open() -> None:
    hooks = Hooks()
    evidence = []
    sink = make_sink(hooks, evidence)

    sink.emit(object())
    sink.emit(Reclaimed("r3", None, 1, "unknown"))

    assert hooks.drafts == []
    assert evidence == []
    assert sink.snapshot().event_count == 0
