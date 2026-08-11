from __future__ import annotations

import hashlib
import json
import os
import stat
import threading
from pathlib import Path

import pytest

import vllm_request_lifecycle_profiler.runtime_hooks as runtime_hooks_module
from vllm_request_lifecycle_profiler.kv_recovery_profile_protocol import (
    PROFILE_ID,
    KVRecoveryProfileConfig,
)
from vllm_request_lifecycle_profiler.kv_recovery_runtime import (
    BoundedKVRecoveryProfileLedger,
)
from vllm_request_lifecycle_profiler.runtime_hooks import (
    JsonlTraceSink,
    RuntimeLifecycleHooks,
    RuntimeTraceConfig,
)
from vllm_request_lifecycle_profiler.runtime_protocol import (
    KV_RECOVERY_COMMUNICATION_MODE,
    RuntimeProvenance,
)

PROCESS_UUID = "1" * 32
CLOCK_DOMAIN_ID = "2" * 32
RUN_ID = "3" * 32
TRACE_ID = "4" * 32
PROVENANCE = RuntimeProvenance("a" * 40, "b" * 40, "c" * 40)


def make_sink(
    tmp_path: Path,
    *,
    write_function=os.write,
) -> JsonlTraceSink:
    return JsonlTraceSink(
        tmp_path / "trace",
        PROVENANCE,
        communication_mode=KV_RECOVERY_COMMUNICATION_MODE,
        kv_recovery_profile_config=KVRecoveryProfileConfig(run_id=RUN_ID),
        clock_ns=lambda: 1000,
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: PROCESS_UUID,
        write_function=write_function,
    )


def block_fields() -> dict[str, object]:
    return {
        "trace_id": TRACE_ID,
        "engine_lifecycle_id": f"{TRACE_ID}:e:0",
        "runtime_request_id": "request-0",
        "request_id_kind": "engine_internal",
        "sample_index": 0,
        "recovery_epoch": 1,
        "episode_id": f"{TRACE_ID}:e:0:k:1",
        "block_set_id": "5" * 64,
        "chunk_index": 0,
        "chunk_count": 1,
        "total_block_count": 1,
        "blocks": (
            {
                "group_index": 0,
                "logical_ordinal": 0,
                "logical_block_id": "6" * 32,
            },
        ),
    }


def read_records(path: Path) -> tuple[list[dict[str, object]], list[bytes]]:
    raw_lines = path.read_bytes().splitlines(keepends=True)
    return [json.loads(raw) for raw in raw_lines], raw_lines


def test_paired_writer_publishes_mode_0600_shards_and_balanced_receipt(
    tmp_path: Path,
) -> None:
    sink = make_sink(tmp_path)

    reference = sink.write_kv_recovery_profile("block_set_chunk", 100, **block_fields())
    result = sink.close()

    assert reference is not None
    assert result.close_outcome == "drained"
    assert result.summary_written
    assert result.profile_summary_written
    assert result.profile_attempted_data_count == 1
    base_path = sink.committed_shard_path
    profile_path = sink.committed_kv_recovery_profile_shard_path
    assert base_path is not None and profile_path is not None
    assert base_path.name == f"trace.rlp.{PROCESS_UUID}.jsonl"
    assert profile_path.name == (f"trace.rlp-kv-recovery.{PROCESS_UUID}.jsonl")
    assert stat.S_IMODE(base_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(profile_path.stat().st_mode) == 0o600

    records, raw_lines = read_records(profile_path)
    assert [record["record_type"] for record in records] == [
        "profile_start",
        "block_set_chunk",
        "profile_summary",
    ]
    start, data, summary = records
    assert start["schema"] == PROFILE_ID
    assert start["process_uuid"] == data["process_uuid"] == summary["process_uuid"]
    assert summary["attempted_data_count"] == 1
    assert summary["written_block_set_chunk_count"] == 1
    assert summary["dropped_data_count"] == 0
    assert (
        summary["content_sha256"]
        == hashlib.sha256(b"".join(raw_lines[:-1])).hexdigest()
    )


def test_profile_serialization_failure_persists_exact_loss_ledger(
    tmp_path: Path,
) -> None:
    sink = make_sink(tmp_path)

    invalid = block_fields()
    invalid["blocks"] = ()
    assert sink.write_kv_recovery_profile("block_set_chunk", 100, **invalid) is None
    assert sink.write_kv_recovery_profile("block_set_chunk", 101, **invalid) is None
    result = sink.close()

    assert result.close_outcome == "drained"
    assert result.profile_summary_written
    assert result.profile_attempted_data_count == 2
    assert result.profile_dropped_data_count == 2
    profile_path = sink.committed_kv_recovery_profile_shard_path
    assert profile_path is not None
    records, _raw_lines = read_records(profile_path)
    loss = next(
        record for record in records if record["record_type"] == "loss_interval"
    )
    summary = records[-1]
    assert loss["reason"] == "serialization_failure"
    assert loss["first_dropped_record_seq"] == 0
    assert loss["last_dropped_record_seq"] == 1
    assert loss["dropped_count"] == 2
    assert loss["block_set_chunk_count"] == 2
    assert summary["attempted_data_count"] == 2
    assert summary["dropped_data_count"] == 2
    assert summary["written_loss_interval_count"] == 1
    assert not sink.kv_recovery_profile_evidence_complete


def test_producer_ledger_drains_into_the_paired_writer(tmp_path: Path) -> None:
    profile_config = KVRecoveryProfileConfig(run_id=RUN_ID)
    sink = make_sink(tmp_path)
    hooks = RuntimeLifecycleHooks(
        RuntimeTraceConfig(
            export_path=tmp_path / "trace",
            provenance=PROVENANCE,
            communication_mode=KV_RECOVERY_COMMUNICATION_MODE,
            kv_recovery_profile_config=profile_config,
        ),
        sink=sink,
    )
    ledger = BoundedKVRecoveryProfileLedger(PROCESS_UUID, hooks=hooks)

    record_id = ledger.write("block_set_chunk", 100, **block_fields())
    result = hooks.close()

    assert record_id == f"{PROCESS_UUID}:k:0"
    assert result is not None and result.profile_summary_written
    assert ledger.attempted_data_count == 1
    records, losses = ledger.snapshot()
    assert len(records) == 1
    assert records[0].record_id == record_id
    assert losses == ()
    profile_path = hooks.committed_kv_recovery_profile_shard_path
    assert profile_path is not None
    persisted, _raw = read_records(profile_path)
    assert persisted[1]["record_id"] == record_id


def test_base_and_profile_use_one_writer_thread(tmp_path: Path) -> None:
    writer_threads: set[int] = set()

    def observed_write(fd: int, raw: bytes | memoryview) -> int:
        writer_threads.add(threading.get_ident())
        return os.write(fd, raw)

    sink = make_sink(tmp_path, write_function=observed_write)
    assert (
        sink.write_kv_recovery_profile("block_set_chunk", 100, **block_fields())
        is not None
    )

    result = sink.close()

    assert result.close_outcome == "drained"
    assert writer_threads == {sink._writer.ident}


def test_profile_publication_failure_retracts_the_base_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = make_sink(tmp_path)
    assert (
        sink.write_kv_recovery_profile("block_set_chunk", 100, **block_fields())
        is not None
    )
    real_replace = os.replace

    def fail_profile_publication(source: Path | str, target: Path | str) -> None:
        if ".rlp-kv-recovery." in str(target) and ".incomplete." in str(source):
            raise OSError("injected profile publication failure")
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", fail_profile_publication)

    result = sink.close()

    assert result.close_outcome == "writer_failure"
    assert not result.summary_written
    assert sink.committed_shard_path is None
    assert sink.committed_kv_recovery_profile_shard_path is None


def test_profile_writer_failure_fails_both_receipts_open_for_serving(
    tmp_path: Path,
) -> None:
    write_count = 0

    def fail_data_write(fd: int, raw: bytes | memoryview) -> int:
        nonlocal write_count
        write_count += 1
        if write_count == 3:
            return 0
        return os.write(fd, raw)

    sink = make_sink(tmp_path, write_function=fail_data_write)
    assert (
        sink.write_kv_recovery_profile("block_set_chunk", 100, **block_fields())
        is not None
    )

    result = sink.close()

    assert result.close_outcome == "writer_failure"
    assert not result.summary_written
    assert not result.profile_summary_written
    assert sink.committed_shard_path is None
    assert sink.committed_kv_recovery_profile_shard_path is None


def test_profile_close_timeout_fails_both_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = threading.Event()
    monkeypatch.setattr(runtime_hooks_module, "CLOSE_TIMEOUT_MS", 30)
    sink = JsonlTraceSink(
        tmp_path / "trace",
        PROVENANCE,
        communication_mode=KV_RECOVERY_COMMUNICATION_MODE,
        kv_recovery_profile_config=KVRecoveryProfileConfig(run_id=RUN_ID),
        clock_ns=lambda: 1000,
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: PROCESS_UUID,
        writer_start_gate=gate,
    )
    assert (
        sink.write_kv_recovery_profile("block_set_chunk", 100, **block_fields())
        is not None
    )

    result = sink.close()

    gate.set()
    assert result.close_outcome == "timeout"
    assert not result.summary_written
    assert not result.profile_summary_written
    assert sink.committed_shard_path is None
    assert sink.committed_kv_recovery_profile_shard_path is None


def test_profile_queue_capacity_is_independent_and_loss_balances(
    tmp_path: Path,
) -> None:
    gate = threading.Event()
    sink = JsonlTraceSink(
        tmp_path / "trace",
        PROVENANCE,
        communication_mode=KV_RECOVERY_COMMUNICATION_MODE,
        kv_recovery_profile_config=KVRecoveryProfileConfig(run_id=RUN_ID),
        clock_ns=lambda: 1000,
        clock_domain_reader=lambda: CLOCK_DOMAIN_ID,
        process_uuid_factory=lambda: PROCESS_UUID,
        writer_start_gate=gate,
    )

    for record_seq in range(4096):
        reference = sink.write_kv_recovery_profile(
            "block_set_chunk", 100 + record_seq, **block_fields()
        )
        assert reference is not None
        assert reference.record_seq == record_seq
    assert (
        sink.write_kv_recovery_profile("block_set_chunk", 5000, **block_fields())
        is None
    )
    gate.set()

    result = sink.close()

    assert result.close_outcome == "drained"
    assert result.attempted_data_count == 0
    assert result.profile_attempted_data_count == 4097
    assert result.profile_dropped_data_count == 1
    profile_path = sink.committed_kv_recovery_profile_shard_path
    assert profile_path is not None
    records, _raw = read_records(profile_path)
    loss = next(
        record for record in records if record["record_type"] == "loss_interval"
    )
    summary = records[-1]
    assert loss["first_dropped_record_seq"] == 4096
    assert loss["last_dropped_record_seq"] == 4096
    assert summary["written_block_set_chunk_count"] == 4096
    assert summary["dropped_data_count"] == 1
