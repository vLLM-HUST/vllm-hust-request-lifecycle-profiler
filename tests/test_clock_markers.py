from __future__ import annotations

import os

import pytest

from vllm_request_lifecycle_profiler.clock_markers import (
    CLOCK_MARKER_CAPACITY_EXHAUSTED_STATUS,
    CLOCK_MARKER_EXPORT_ENV,
    CLOCK_MARKER_MAX_RECORDS_ENV,
    CLOCK_MARKER_TSV_HEADER,
    AscendClockMarkerCollector,
)


class FakeAscendRuntime:
    def __init__(
        self,
        *,
        create_status: int = 0,
        record_status: int = 0,
        sync_status: int = 0,
        destroy_status: int = 0,
    ) -> None:
        self.create_status = create_status
        self.record_status = record_status
        self.sync_status = sync_status
        self.destroy_status = destroy_status
        self.calls: list[tuple[object, ...]] = []

    def create_timeline_event(self) -> tuple[int, int]:
        self.calls.append(("create",))
        return self.create_status, 0 if self.create_status else 1234

    def record_event(self, event: int, stream: int) -> int:
        self.calls.append(("record", event, stream))
        return self.record_status

    def synchronize_event(self, event: int) -> int:
        self.calls.append(("sync", event))
        return self.sync_status

    def destroy_event(self, event: int) -> int:
        self.calls.append(("destroy", event))
        return self.destroy_status


def test_clock_marker_collector_writes_resolvable_host_bracket(tmp_path) -> None:
    marker_path = tmp_path / "clock_marker_brackets.tsv"
    runtime = FakeAscendRuntime()
    timestamps = iter([1_000_000, 1_000_040, 1_000_200])

    with AscendClockMarkerCollector(
        marker_path,
        device_id=6,
        stream_handle=0xABC,
        stream_id=17,
        call_site="unit-test",
        runtime=runtime,
        time_ns=lambda: next(timestamps),
    ) as collector:
        bracket = collector.record("marker-000")

    assert bracket.host_before_ns == 1_000_000
    assert bracket.record_after_ns == 1_000_040
    assert bracket.host_after_ns == 1_000_200
    assert bracket.host_pid == os.getpid()
    assert bracket.device_id == 6
    assert bracket.stream_id == 17
    assert bracket.return_status == 0
    assert runtime.calls == [
        ("create",),
        ("record", 1234, 0xABC),
        ("sync", 1234),
        ("destroy", 1234),
    ]

    rows = marker_path.read_text(encoding="utf-8").splitlines()
    assert rows[0] == CLOCK_MARKER_TSV_HEADER.rstrip("\n")
    fields = rows[1].split("\t")
    assert fields[0:4] == [
        "marker-000",
        "1000000",
        "1000040",
        "1000200",
    ]
    assert fields[4] == str(os.getpid())
    assert fields[6:] == ["6", "17", "unit-test", "0"]


def test_clock_marker_collector_retains_failed_record_without_sync(tmp_path) -> None:
    marker_path = tmp_path / "failed.tsv"
    runtime = FakeAscendRuntime(record_status=507000)
    timestamps = iter([100, 105, 110])
    collector = AscendClockMarkerCollector(
        marker_path,
        device_id=6,
        runtime=runtime,
        time_ns=lambda: next(timestamps),
    )
    bracket = collector.record("failed-marker")
    collector.close()

    assert bracket.return_status == 507000
    assert not any(call[0] == "sync" for call in runtime.calls)
    assert marker_path.read_text(encoding="utf-8").splitlines()[1].endswith("\t507000")


def test_clock_marker_collector_is_opt_in_and_fails_closed(tmp_path) -> None:
    assert AscendClockMarkerCollector.from_env(device_id=6, env={}) is None
    runtime = FakeAscendRuntime(create_status=123)
    with pytest.raises(RuntimeError, match="status 123"):
        AscendClockMarkerCollector(
            tmp_path / "unused.tsv", device_id=6, runtime=runtime
        )
    assert not (tmp_path / "unused.tsv").exists()

    configured_runtime = FakeAscendRuntime()
    collector = AscendClockMarkerCollector.from_env(
        device_id=6,
        env={CLOCK_MARKER_EXPORT_ENV: str(tmp_path / "from-env.tsv")},
        runtime=configured_runtime,
        time_ns=lambda: 1,
    )
    assert collector is not None
    collector.close()


def test_clock_marker_ids_and_call_sites_are_strict_tsv_fields(tmp_path) -> None:
    with pytest.raises(ValueError, match="call_site"):
        AscendClockMarkerCollector(
            tmp_path / "unused.tsv",
            device_id=6,
            call_site="bad\tfield",
            runtime=FakeAscendRuntime(),
        )

    collector = AscendClockMarkerCollector(
        tmp_path / "strict.tsv", device_id=6, runtime=FakeAscendRuntime()
    )
    with pytest.raises(ValueError, match="marker_id"):
        collector.record("bad\nmarker")
    with pytest.raises(ValueError, match="printable ASCII"):
        collector.record("bad\x00marker")
    with pytest.raises(ValueError, match="128 bytes"):
        collector.record("x" * 129)
    collector.close()


def test_clock_marker_rejects_non_monotonic_realtime_bracket(tmp_path) -> None:
    timestamps = iter([100, 90, 110])
    collector = AscendClockMarkerCollector(
        tmp_path / "clock-step.tsv",
        device_id=6,
        runtime=FakeAscendRuntime(),
        time_ns=lambda: next(timestamps),
    )
    with pytest.raises(RuntimeError, match="moved backward"):
        collector.record("clock-step")
    collector.close()


def test_clock_marker_capacity_emits_one_sentinel_then_drops(tmp_path) -> None:
    marker_path = tmp_path / "bounded.tsv"
    runtime = FakeAscendRuntime()
    timestamps = iter([100, 110, 120, 200, 210, 220, 300])
    collector = AscendClockMarkerCollector(
        marker_path,
        device_id=6,
        runtime=runtime,
        time_ns=lambda: next(timestamps),
        max_records=2,
    )

    assert collector.record("marker-0") is not None
    assert collector.record("marker-1") is not None
    sentinel = collector.record("marker-2")
    assert sentinel is not None
    assert sentinel.return_status == CLOCK_MARKER_CAPACITY_EXHAUSTED_STATUS
    assert collector.capacity_exhausted is True
    assert collector.record("marker-3") is None
    collector.close()

    rows = marker_path.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 4
    assert rows[-1].startswith("capacity-exhausted-")
    assert rows[-1].endswith(f"\t{CLOCK_MARKER_CAPACITY_EXHAUSTED_STATUS}")
    assert [call[0] for call in runtime.calls].count("record") == 2
    assert [call[0] for call in runtime.calls].count("sync") == 2


def test_clock_marker_capacity_can_be_configured_from_env(tmp_path) -> None:
    collector = AscendClockMarkerCollector.from_env(
        device_id=6,
        env={
            CLOCK_MARKER_EXPORT_ENV: str(tmp_path / "from-env.tsv"),
            CLOCK_MARKER_MAX_RECORDS_ENV: "7",
        },
        runtime=FakeAscendRuntime(),
        time_ns=lambda: 1,
    )
    assert collector is not None
    assert collector.max_records == 7
    collector.close()


@pytest.mark.parametrize("value", ["0", "1000001", "not-an-int"])
def test_clock_marker_capacity_rejects_invalid_env_values(tmp_path, value) -> None:
    with pytest.raises(ValueError, match="max_records|must be an integer"):
        AscendClockMarkerCollector.from_env(
            device_id=6,
            env={
                CLOCK_MARKER_EXPORT_ENV: str(tmp_path / "unused.tsv"),
                CLOCK_MARKER_MAX_RECORDS_ENV: value,
            },
            runtime=FakeAscendRuntime(),
        )
