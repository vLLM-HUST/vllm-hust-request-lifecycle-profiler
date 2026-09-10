from __future__ import annotations

import sqlite3

import pytest

from vllm_request_lifecycle_profiler.traceloom_adapter import (
    TraceLoomAdapterError,
    inspect_traceloom_schema,
    resolve_explicit_links,
)


def _database(path):
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE traceloom_event (
          event_id TEXT, source_table TEXT, source_key TEXT
        );
        CREATE TABLE traceloom_event_source (
          event_id TEXT, source_ordinal INTEGER, source_table TEXT,
          source_key TEXT, source_role TEXT
        );
        CREATE TABLE traceloom_anchor (anchor_id TEXT, event_id TEXT);
        CREATE TABLE traceloom_semantic_tree (tree_id TEXT);
        CREATE TABLE traceloom_semantic_node (node_id TEXT, tree_id TEXT);
        CREATE TABLE traceloom_semantic_edge (
          parent_node_id TEXT, child_node_id TEXT, tree_id TEXT
        );
        CREATE TABLE traceloom_viz_node_anchor (
          node_id TEXT, occurrence_idx INTEGER, anchor_id TEXT
        );
        CREATE TABLE traceloom_tree_node_occurrence (
          node_id TEXT, occurrence_idx INTEGER, start_ns INTEGER, end_ns INTEGER,
          total_us REAL, self_us REAL
        );
        CREATE TABLE traceloom_runtime_call (
          runtime_call_id TEXT, source_table TEXT, source_key TEXT
        );
        CREATE TABLE traceloom_device_work (
          device_work_id TEXT, event_id TEXT, source_table TEXT, source_key TEXT
        );
        CREATE TABLE traceloom_runtime_device_relation (
          relation_id TEXT, runtime_call_id TEXT, device_work_id TEXT,
          support_state TEXT
        );
        CREATE TABLE traceloom_v_sync_runtime_call (
          sync_action_id TEXT, event_id TEXT, device_source_table TEXT,
          device_source_key TEXT, support_state TEXT
        );
        INSERT INTO traceloom_event VALUES ('event-1', 'TASK', 'row-7');
        INSERT INTO traceloom_event_source
          VALUES ('event-1', 0, 'TASK', 'row-7', 'raw_event');
        INSERT INTO traceloom_anchor VALUES ('anchor-1', 'event-1');
        INSERT INTO traceloom_semantic_tree VALUES ('tree-1');
        INSERT INTO traceloom_semantic_node VALUES ('node-1', 'tree-1');
        INSERT INTO traceloom_viz_node_anchor VALUES ('node-1', 0, 'anchor-1');
        INSERT INTO traceloom_tree_node_occurrence
          VALUES ('node-1', 0, 100, 200, 0.1, 0.1);
        INSERT INTO traceloom_runtime_call
          VALUES ('call-1', 'RUNTIME_API', 'call-row-1');
        INSERT INTO traceloom_device_work
          VALUES ('work-1', 'event-1', 'TASK', 'row-7');
        INSERT INTO traceloom_runtime_device_relation
          VALUES ('relation-1', 'call-1', 'work-1', 'supported_exact');
        INSERT INTO traceloom_v_sync_runtime_call
          VALUES ('sync-1', 'event-1', 'TASK', 'row-7', 'supported_exact');
        """
    )
    connection.commit()
    connection.close()
    return path


def _link():
    return {
        "span_id": "span-1",
        "trace_id": "trace-1",
        "engine_lifecycle_id": "life-1",
        "recovery_epoch": 0,
        "request_id": "request-1",
        "tree_id": "tree-1",
        "node_id": "node-1",
        "occurrence_idx": 0,
        "anchor_id": "anchor-1",
        "event_id": "event-1",
        "link_kind": "execution_support",
        "owner": "worker",
        "clock_domain": "device",
        "evidence_source": "traceloom_sqlite",
        "support_state": "supported_exact",
    }


def test_schema_inspection_and_explicit_drill_down(tmp_path):
    database = _database(tmp_path / "trace.db")
    report = inspect_traceloom_schema(database)
    assert report["core_complete"]
    assert report["missing_support_relations"] == []

    resolved = resolve_explicit_links(database, [_link()])
    assert resolved[0]["resolved"]
    assert resolved[0]["tree_occurrence"] == {
        "node_id": "node-1",
        "occurrence_idx": 0,
        "start_ns": 100,
        "end_ns": 200,
        "total_us": 0.1,
        "self_us": 0.1,
    }
    assert resolved[0]["source_lineage"] == [
        {"source_table": "TASK", "source_key": "row-7", "source_role": "raw_event"}
    ]


def test_no_link_is_inferred_from_timestamp_overlap(tmp_path):
    database = _database(tmp_path / "trace.db")
    assert resolve_explicit_links(database, []) == []


def test_ambiguous_link_is_preserved_as_residual(tmp_path):
    database = _database(tmp_path / "trace.db")
    link = _link()
    link.update(
        {
            "support_state": "ambiguous_request_membership",
            "reason": "request-to-batch roster was unavailable",
        }
    )
    resolved = resolve_explicit_links(database, [link])
    assert not resolved[0]["resolved"]
    assert resolved[0]["source_lineage"] == []


def test_event_only_and_runtime_relation_links_are_consumed_as_applicable(tmp_path):
    database = _database(tmp_path / "trace.db")
    event_only = _link()
    for key in ("tree_id", "node_id", "occurrence_idx", "anchor_id"):
        event_only.pop(key)
    event_only["runtime_relation_id"] = "relation-1"
    event_only["runtime_call_id"] = "call-1"
    event_only["device_work_id"] = "work-1"
    resolved = resolve_explicit_links(database, [event_only])
    assert resolved[0]["resolved"]
    assert {row["source_role"] for row in resolved[0]["source_lineage"]} == {
        "raw_event",
        "runtime_call",
        "device_work",
    }


def test_duplicate_identity_is_rejected_as_ambiguous(tmp_path):
    database = _database(tmp_path / "trace.db")
    connection = sqlite3.connect(database)
    connection.execute("INSERT INTO traceloom_semantic_tree VALUES ('tree-1')")
    connection.commit()
    connection.close()
    with pytest.raises(TraceLoomAdapterError, match="ambiguous tree"):
        resolve_explicit_links(database, [_link()])


def test_supported_link_must_follow_exact_membership(tmp_path):
    database = _database(tmp_path / "trace.db")
    link = _link()
    link["anchor_id"] = "anchor-other"
    with pytest.raises(TraceLoomAdapterError, match="exact anchor membership"):
        resolve_explicit_links(database, [link])


def test_runtime_relation_must_resolve_to_the_same_event(tmp_path):
    database = _database(tmp_path / "trace.db")
    connection = sqlite3.connect(database)
    connection.execute(
        "INSERT INTO traceloom_event VALUES ('event-2', 'TASK', 'row-8')"
    )
    connection.execute(
        "INSERT INTO traceloom_device_work "
        "VALUES ('work-2', 'event-2', 'TASK', 'row-8')"
    )
    connection.execute(
        "INSERT INTO traceloom_runtime_device_relation "
        "VALUES ('relation-2', 'call-1', 'work-2', 'supported_exact')"
    )
    connection.commit()
    connection.close()
    link = _link()
    for key in ("tree_id", "node_id", "occurrence_idx", "anchor_id"):
        link.pop(key)
    link["runtime_relation_id"] = "relation-2"
    with pytest.raises(TraceLoomAdapterError, match="inconsistent event identity"):
        resolve_explicit_links(database, [link])


def test_invalid_database_inputs_are_normalized_to_adapter_errors(tmp_path):
    with pytest.raises(TraceLoomAdapterError, match="path must be a pathlib.Path"):
        resolve_explicit_links("trace.db", [_link()])  # type: ignore[arg-type]

    malformed = tmp_path / "malformed.db"
    malformed.write_text("not a SQLite database", encoding="utf-8")
    with pytest.raises(TraceLoomAdapterError, match="cannot inspect"):
        inspect_traceloom_schema(malformed)


def test_missing_source_lineage_identity_is_rejected(tmp_path):
    database = _database(tmp_path / "trace.db")
    connection = sqlite3.connect(database)
    connection.execute(
        "UPDATE traceloom_event_source SET source_key = NULL WHERE event_id = 'event-1'"
    )
    connection.commit()
    connection.close()
    with pytest.raises(TraceLoomAdapterError, match="lineage identity is malformed"):
        resolve_explicit_links(database, [_link()])
