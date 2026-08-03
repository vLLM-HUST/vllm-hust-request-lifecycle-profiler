"""KV preemption/restore timeline validation and latency decomposition.

This schema is intentionally separate from the base request lifecycle stages.
It can be emitted only for pressure episodes without making historical request
traces appear incomplete.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum


class KVRecoveryStage(str, Enum):
    PREEMPT = "preempt"
    RESTORE_START = "restore_start"
    RESTORE_DONE = "restore_done"
    SCHEDULER_WAKEUP = "scheduler_wakeup"
    REQUEUE = "requeue"
    ADMISSION = "admission"
    FIRST_COMPUTE = "first_prefill_or_decode"


@dataclass(frozen=True)
class KVRecoveryEvent:
    request_id: str
    sequence_id: str
    stage: KVRecoveryStage
    timestamp_ms: float
    block_ids: tuple[str, ...] = ()
    bytes_moved: int | None = None
    reason: str | None = None


@dataclass(frozen=True)
class KVRecoveryDecomposition:
    request_id: str
    sequence_id: str
    block_count: int
    bytes_moved: int
    copy_ms: float
    restore_to_wakeup_ms: float
    wakeup_to_admission_ms: float
    restore_to_admission_ms: float
    admission_to_first_compute_ms: float
    total_recovery_ms: float
    requeue_count: int
    requeue_reasons: tuple[str, ...]


_REQUIRED_STAGES = (
    KVRecoveryStage.PREEMPT,
    KVRecoveryStage.RESTORE_START,
    KVRecoveryStage.RESTORE_DONE,
    KVRecoveryStage.SCHEDULER_WAKEUP,
    KVRecoveryStage.ADMISSION,
    KVRecoveryStage.FIRST_COMPUTE,
)


def decompose_kv_recovery(
    events: Iterable[KVRecoveryEvent],
) -> KVRecoveryDecomposition:
    """Validate one pressure episode and separate copy from scheduler waiting."""

    ordered = sorted(events, key=lambda event: event.timestamp_ms)
    if not ordered:
        raise ValueError("kv recovery timeline is empty")

    request_ids = {event.request_id for event in ordered}
    sequence_ids = {event.sequence_id for event in ordered}
    if len(request_ids) != 1 or len(sequence_ids) != 1:
        raise ValueError("all recovery events must use one stable request/sequence id")

    by_stage: dict[KVRecoveryStage, KVRecoveryEvent] = {}
    for event in ordered:
        if event.stage is KVRecoveryStage.REQUEUE:
            continue
        if event.stage in by_stage:
            raise ValueError(f"duplicate recovery milestone: {event.stage.value}")
        by_stage[event.stage] = event

    missing = [stage.value for stage in _REQUIRED_STAGES if stage not in by_stage]
    if missing:
        raise ValueError(f"missing recovery milestones: {', '.join(missing)}")

    milestones = [by_stage[stage] for stage in _REQUIRED_STAGES]
    timestamps = [event.timestamp_ms for event in milestones]
    if timestamps != sorted(timestamps):
        raise ValueError("recovery milestones are not causally ordered")

    restore_start = by_stage[KVRecoveryStage.RESTORE_START]
    restore_done = by_stage[KVRecoveryStage.RESTORE_DONE]
    if not restore_start.block_ids:
        raise ValueError("restore_start must carry stable block ids")
    if restore_start.block_ids != restore_done.block_ids:
        raise ValueError("restore_start/restore_done block ids differ")
    if restore_done.bytes_moved is None or restore_done.bytes_moved <= 0:
        raise ValueError("restore_done must carry positive bytes_moved")

    preempt = by_stage[KVRecoveryStage.PREEMPT]
    wakeup = by_stage[KVRecoveryStage.SCHEDULER_WAKEUP]
    admission = by_stage[KVRecoveryStage.ADMISSION]
    first_compute = by_stage[KVRecoveryStage.FIRST_COMPUTE]
    requeues = [event for event in ordered if event.stage is KVRecoveryStage.REQUEUE]
    if any(not event.reason for event in requeues):
        raise ValueError("every requeue event must carry a reason")

    return KVRecoveryDecomposition(
        request_id=ordered[0].request_id,
        sequence_id=ordered[0].sequence_id,
        block_count=len(restore_start.block_ids),
        bytes_moved=restore_done.bytes_moved,
        copy_ms=restore_done.timestamp_ms - restore_start.timestamp_ms,
        restore_to_wakeup_ms=wakeup.timestamp_ms - restore_done.timestamp_ms,
        wakeup_to_admission_ms=admission.timestamp_ms - wakeup.timestamp_ms,
        restore_to_admission_ms=admission.timestamp_ms - restore_done.timestamp_ms,
        admission_to_first_compute_ms=(
            first_compute.timestamp_ms - admission.timestamp_ms
        ),
        total_recovery_ms=first_compute.timestamp_ms - preempt.timestamp_ms,
        requeue_count=len(requeues),
        requeue_reasons=tuple(event.reason or "" for event in requeues),
    )


__all__ = [
    "KVRecoveryDecomposition",
    "KVRecoveryEvent",
    "KVRecoveryStage",
    "decompose_kv_recovery",
]
