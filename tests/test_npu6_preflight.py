from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / ".benchmarks" / "preflight_npu6_trace_probe.py"
SPEC = importlib.util.spec_from_file_location("preflight_npu6_trace_probe", SCRIPT_PATH)
assert SPEC is not None
preflight = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(preflight)


def test_validate_trace_export_accepts_jsonl_lifecycle_schema(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "request_id": "req-1",
                        "stage": "received",
                        "timestamp_ms": 1.0,
                        "metadata": {"client_request_id": "req-1"},
                    }
                ),
                json.dumps(
                    {
                        "request_id": "req-1",
                        "stage": "tokenized",
                        "timestamp_ms": 2.0,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = preflight._validate_trace_export(str(trace_path))

    assert result["ok"] is True
    assert result["record_count_checked"] == 2
    assert result["timestamp_unit"] == "milliseconds"


def test_validate_trace_export_reports_missing_required_fields(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(json.dumps({"request_id": "req-1", "stage": "received"}) + "\n", encoding="utf-8")

    result = preflight._validate_trace_export(str(trace_path))

    assert result["ok"] is False
    assert result["missing_rows"] == [{"index": 0, "missing": ["timestamp_ms"]}]


def test_npu_smi_parser_finds_requested_npu_process() -> None:
    output = """
| NPU     Chip              | Process id    | Process name             | Process memory(MB)      |
+===========================+===============+====================================================+
| 6       0                 | 12345         | python3                  | 4096                    |
+===========================+===============+====================================================+
"""

    processes = preflight._npu_processes(output, 6)

    assert processes == [
        {
            "npu": "6",
            "chip": "0",
            "pid": "12345",
            "process_name": "python3",
            "process_memory_mb": "4096",
        }
    ]


def test_blockers_include_missing_trace_and_npu_process() -> None:
    metadata = {
        "ascend_runtime_root": {"ok": True},
        "model_path": "/models/demo",
        "model_path_exists": True,
        "models_endpoint": {"ok": True},
        "trace_export": {"ok": False, "error": "trace_export_path_not_found"},
        "npu_smi": {"ok": True, "has_process_on_requested_npu": False},
    }

    assert preflight._blockers(metadata) == [
        "trace_export_invalid:trace_export_path_not_found",
        "no_process_on_npu6",
    ]


def test_blocked_preflight_removes_stale_ready_marker(tmp_path: Path) -> None:
    ready = tmp_path / "READY.txt"
    ready.write_text("stale readiness\n", encoding="utf-8")
    metadata = {}

    preflight._write_blocked(tmp_path, ["models_endpoint_failed"], metadata)

    assert not ready.exists()
    assert (tmp_path / "BLOCKED.txt").exists()
    assert metadata["preflight_passed"] is False
