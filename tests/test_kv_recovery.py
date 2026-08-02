from __future__ import annotations

import pytest

from vllm_request_lifecycle_profiler.kv_recovery import KVRecoveryEvent
from vllm_request_lifecycle_profiler.kv_recovery import KVRecoveryStage
from vllm_request_lifecycle_profiler.kv_recovery import decompose_kv_recovery


def _event(stage, timestamp, **kwargs):
    return KVRecoveryEvent("req-1", "seq-1", stage, timestamp, **kwargs)


def test_decomposes_copy_and_restore_to_admission_wait() -> None:
    result = decompose_kv_recovery(
        [
            _event(KVRecoveryStage.PREEMPT, 0),
            _event(
                KVRecoveryStage.RESTORE_START,
                10,
                block_ids=("b-1", "b-2"),
            ),
            _event(
                KVRecoveryStage.RESTORE_DONE,
                34,
                block_ids=("b-1", "b-2"),
                bytes_moved=8192,
            ),
            _event(KVRecoveryStage.SCHEDULER_WAKEUP, 41),
            _event(KVRecoveryStage.REQUEUE, 45, reason="token_budget"),
            _event(KVRecoveryStage.ADMISSION, 70),
            _event(KVRecoveryStage.FIRST_COMPUTE, 75),
        ]
    )
    assert result.copy_ms == 24
    assert result.restore_to_wakeup_ms == 7
    assert result.wakeup_to_admission_ms == 29
    assert result.restore_to_admission_ms == 36
    assert result.admission_to_first_compute_ms == 5
    assert result.total_recovery_ms == 75
    assert result.block_count == 2
    assert result.bytes_moved == 8192
    assert result.requeue_reasons == ("token_budget",)


@pytest.mark.parametrize(
    ("events", "message"),
    [
        ([], "empty"),
        (
            [
                KVRecoveryEvent(
                    "req-1", "seq-1", KVRecoveryStage.PREEMPT, 0
                ),
                KVRecoveryEvent(
                    "req-2", "seq-1", KVRecoveryStage.RESTORE_START, 1
                ),
            ],
            "stable request/sequence id",
        ),
    ],
)
def test_rejects_unattributable_timelines(events, message) -> None:
    with pytest.raises(ValueError, match=message):
        decompose_kv_recovery(events)


def test_rejects_block_identity_change() -> None:
    events = [
        _event(KVRecoveryStage.PREEMPT, 0),
        _event(KVRecoveryStage.RESTORE_START, 1, block_ids=("b-1",)),
        _event(
            KVRecoveryStage.RESTORE_DONE,
            2,
            block_ids=("b-2",),
            bytes_moved=4096,
        ),
        _event(KVRecoveryStage.SCHEDULER_WAKEUP, 3),
        _event(KVRecoveryStage.ADMISSION, 4),
        _event(KVRecoveryStage.FIRST_COMPUTE, 5),
    ]
    with pytest.raises(ValueError, match="block ids differ"):
        decompose_kv_recovery(events)
