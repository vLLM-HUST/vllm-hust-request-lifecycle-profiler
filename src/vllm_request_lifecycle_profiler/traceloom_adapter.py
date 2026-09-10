"""Narrow adapter for TraceLoom's augmented SQLite evidence.

TraceLoom owns execution trees and profiler-row lineage.  This adapter only
validates explicit request/lifecycle join keys and resolves their drill-down
references.  It never invents membership from timestamp overlap.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

CORE_RELATIONS = {
    "traceloom_event",
    "traceloom_event_source",
    "traceloom_anchor",
    "traceloom_semantic_tree",
    "traceloom_semantic_node",
    "traceloom_semantic_edge",
    "traceloom_viz_node_anchor",
    "traceloom_tree_node_occurrence",
}

SUPPORT_RELATIONS = {
    "traceloom_runtime_call",
    "traceloom_device_work",
    "traceloom_runtime_device_relation",
    "traceloom_v_sync_runtime_call",
}

OPTIONAL_GRAPH_RELATIONS = {
    "traceloom_cuda_graph_replay",
    "traceloom_cuda_graph_envelope",
}

SUPPORTED_STATES = {"supported_exact", "supported_deterministic"}
MAX_LINKS = 4096


class TraceLoomAdapterError(ValueError):
    """The SQLite evidence cannot support an explicit lifecycle join."""


def inspect_traceloom_schema(database: Path) -> dict[str, Any]:
    """Report relation availability without claiming missing optional evidence."""

    try:
        with _connect_read_only(database) as connection:
            available = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
                )
            }
    except sqlite3.Error as exc:
        raise TraceLoomAdapterError(
            f"cannot inspect TraceLoom database: {exc}"
        ) from exc
    return {
        "core_complete": CORE_RELATIONS <= available,
        "missing_core_relations": sorted(CORE_RELATIONS - available),
        "available_support_relations": sorted(SUPPORT_RELATIONS & available),
        "missing_support_relations": sorted(SUPPORT_RELATIONS - available),
        "available_optional_graph_relations": sorted(
            OPTIONAL_GRAPH_RELATIONS & available
        ),
    }


def resolve_explicit_links(
    database: Path, links: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Resolve already-established links to TraceLoom-owned source lineage.

    Empty input produces empty output even if timestamps happen to overlap.
    Missing or ambiguous links are preserved as residual evidence with their
    supplied reason; supported links must be drillable through stored keys.
    """

    link_list = list(links)
    if not link_list:
        return []
    if len(link_list) > MAX_LINKS:
        raise TraceLoomAdapterError("link count exceeds the repository record capacity")

    resolved: list[dict[str, Any]] = []
    try:
        with _connect_read_only(database) as connection:
            connection.row_factory = sqlite3.Row
            for index, link in enumerate(link_list):
                support_state = link.get("support_state")
                if support_state not in SUPPORTED_STATES:
                    reason = link.get("reason")
                    if not isinstance(reason, str) or not reason:
                        raise TraceLoomAdapterError(
                            f"link {index} needs a reason for residual evidence"
                        )
                    resolved.append({**link, "resolved": False, "source_lineage": []})
                    continue
                resolved.append(_resolve_supported_link(connection, link, index))
    except sqlite3.Error as exc:
        raise TraceLoomAdapterError(f"cannot read TraceLoom database: {exc}") from exc
    return resolved


def _resolve_supported_link(
    connection: sqlite3.Connection, link: Mapping[str, Any], index: int
) -> dict[str, Any]:
    lineage: list[dict[str, Any]] = []
    resolved_ids: set[str] = set()
    occurrence: dict[str, Any] | None = None
    tree_keys = ("tree_id", "node_id", "occurrence_idx", "anchor_id")
    if any(link.get(key) is not None for key in tree_keys):
        if not all(link.get(key) is not None for key in tree_keys):
            raise TraceLoomAdapterError(
                f"supported link {index} has a partial tree drill-down chain"
            )
        event_id, occurrence = _resolve_tree_chain(connection, link, index)
        resolved_ids.add(event_id)
    if link.get("event_id") is not None:
        resolved_ids.add(str(link["event_id"]))
    if link.get("runtime_relation_id") is not None:
        relation_lineage, relation_event_id = _resolve_runtime_relation(
            connection, link, index
        )
        lineage.extend(relation_lineage)
        if relation_event_id is not None:
            resolved_ids.add(relation_event_id)
    else:
        if link.get("runtime_call_id") is not None:
            lineage.append(
                _resolve_source_row(
                    connection,
                    "traceloom_runtime_call",
                    "runtime_call_id",
                    str(link["runtime_call_id"]),
                    index,
                    "runtime_call",
                )
            )
        if link.get("device_work_id") is not None:
            device_row = _unique_row(
                connection,
                "SELECT event_id, source_table, source_key FROM traceloom_device_work "
                "WHERE device_work_id = ?",
                (link["device_work_id"],),
                index,
                "device work",
            )
            lineage.append(_lineage_row(device_row, "device_work"))
            if device_row["event_id"] is not None:
                resolved_ids.add(str(device_row["event_id"]))
    if link.get("sync_action_id") is not None:
        sync_row = _unique_row(
            connection,
            "SELECT event_id, device_source_table AS source_table, "
            "device_source_key AS source_key FROM traceloom_v_sync_runtime_call "
            "WHERE sync_action_id = ? AND support_state IN "
            "('supported_exact', 'supported_deterministic')",
            (link["sync_action_id"],),
            index,
            "synchronization action",
        )
        lineage.append(_lineage_row(sync_row, "synchronization"))
        if sync_row["event_id"] is not None:
            resolved_ids.add(str(sync_row["event_id"]))
    graph_event_id = link.get("graph_event_id")
    graph_event_row = None
    if graph_event_id is not None:
        graph_row = _unique_row(
            connection,
            "SELECT event_id FROM traceloom_cuda_graph_replay WHERE graph_event_id = ?",
            (graph_event_id,),
            index,
            "graph replay",
        )
        graph_event_row = str(graph_row["event_id"])
    if link.get("graph_envelope_id") is not None:
        envelope_row = _unique_row(
            connection,
            "SELECT graph_event_id, child_event_id FROM traceloom_cuda_graph_envelope "
            "WHERE envelope_id = ?",
            (link["graph_envelope_id"],),
            index,
            "graph envelope",
        )
        if graph_event_id is not None and str(envelope_row["graph_event_id"]) != str(
            graph_event_id
        ):
            raise TraceLoomAdapterError(
                f"supported link {index} has inconsistent graph envelope identity"
            )
        resolved_ids.add(str(envelope_row["child_event_id"]))
    elif graph_event_row is not None:
        resolved_ids.add(graph_event_row)
    if not resolved_ids and not lineage:
        raise TraceLoomAdapterError(
            f"supported link {index} contains no applicable TraceLoom identity"
        )
    declared_event = link.get("event_id")
    if (
        declared_event is not None
        and resolved_ids
        and resolved_ids != {str(declared_event)}
    ):
        raise TraceLoomAdapterError(
            f"supported link {index} has inconsistent event identity"
        )
    for event_id in sorted(resolved_ids):
        lineage.extend(_event_lineage(connection, event_id, index))
    lineage = _deduplicate_lineage(lineage)
    return {
        **link,
        "resolved": True,
        "source_lineage": lineage,
        "tree_occurrence": occurrence,
    }


def _resolve_tree_chain(
    connection: sqlite3.Connection, link: Mapping[str, Any], index: int
) -> tuple[str, dict[str, Any]]:
    tree_id = link["tree_id"]
    node_id = link["node_id"]
    occurrence_idx = link["occurrence_idx"]
    anchor_id = link["anchor_id"]
    _unique_row(
        connection,
        "SELECT tree_id FROM traceloom_semantic_tree WHERE tree_id = ?",
        (tree_id,),
        index,
        "tree",
    )
    node = _unique_row(
        connection,
        "SELECT tree_id FROM traceloom_semantic_node WHERE node_id = ?",
        (node_id,),
        index,
        "tree node",
    )
    if node["tree_id"] != tree_id:
        raise TraceLoomAdapterError(
            f"supported link {index} has inconsistent tree/node identity"
        )
    occurrence = _unique_row(
        connection,
        "SELECT node_id, occurrence_idx, start_ns, end_ns, total_us, self_us "
        "FROM traceloom_tree_node_occurrence "
        "WHERE node_id = ? AND occurrence_idx = ?",
        (node_id, occurrence_idx),
        index,
        "tree occurrence",
    )
    _unique_row(
        connection,
        "SELECT node_id FROM traceloom_viz_node_anchor "
        "WHERE node_id = ? AND occurrence_idx = ? AND anchor_id = ?",
        (node_id, occurrence_idx, anchor_id),
        index,
        "exact anchor membership",
    )
    anchor = _unique_row(
        connection,
        "SELECT event_id FROM traceloom_anchor WHERE anchor_id = ?",
        (anchor_id,),
        index,
        "anchor",
    )
    return str(anchor["event_id"]), {
        "node_id": occurrence["node_id"],
        "occurrence_idx": occurrence["occurrence_idx"],
        "start_ns": occurrence["start_ns"],
        "end_ns": occurrence["end_ns"],
        "total_us": occurrence["total_us"],
        "self_us": occurrence["self_us"],
    }


def _resolve_runtime_relation(
    connection: sqlite3.Connection, link: Mapping[str, Any], index: int
) -> tuple[list[dict[str, Any]], str | None]:
    relation = _unique_row(
        connection,
        "SELECT runtime_call_id, device_work_id, support_state FROM "
        "traceloom_runtime_device_relation WHERE relation_id = ?",
        (link["runtime_relation_id"],),
        index,
        "runtime/device relation",
    )
    if relation["support_state"] not in SUPPORTED_STATES:
        raise TraceLoomAdapterError(
            f"supported link {index} references an unsupported runtime/device relation"
        )
    for key in ("runtime_call_id", "device_work_id"):
        declared = link.get(key)
        if declared is not None and declared != relation[key]:
            raise TraceLoomAdapterError(
                f"supported link {index} has inconsistent {key}"
            )
    lineage: list[dict[str, Any]] = []
    event_id = None
    if relation["runtime_call_id"] is not None:
        lineage.append(
            _resolve_source_row(
                connection,
                "traceloom_runtime_call",
                "runtime_call_id",
                str(relation["runtime_call_id"]),
                index,
                "runtime_call",
            )
        )
    if relation["device_work_id"] is not None:
        row = _unique_row(
            connection,
            "SELECT event_id, source_table, source_key FROM traceloom_device_work "
            "WHERE device_work_id = ?",
            (relation["device_work_id"],),
            index,
            "device work",
        )
        lineage.append(_lineage_row(row, "device_work"))
        if row["event_id"] is not None:
            event_id = str(row["event_id"])
    return lineage, event_id


def _resolve_source_row(
    connection: sqlite3.Connection,
    relation: str,
    identity_column: str,
    identity: str,
    index: int,
    role: str,
) -> dict[str, Any]:
    row = _unique_row(
        connection,
        f"SELECT source_table, source_key FROM {relation} WHERE {identity_column} = ?",
        (identity,),
        index,
        role,
    )
    return _lineage_row(row, role)


def _event_lineage(
    connection: sqlite3.Connection, event_id: str, index: int
) -> list[dict[str, Any]]:
    event = _unique_row(
        connection,
        "SELECT source_table, source_key FROM traceloom_event WHERE event_id = ?",
        (event_id,),
        index,
        "event",
    )
    sources = connection.execute(
        "SELECT source_table, source_key, source_role FROM traceloom_event_source "
        "WHERE event_id = ? ORDER BY source_ordinal",
        (event_id,),
    ).fetchall()
    if sources:
        return [
            _lineage_row(row, row["source_role"] or "event_source") for row in sources
        ]
    return [_lineage_row(event, "event")]


def _unique_row(
    connection: sqlite3.Connection,
    query: str,
    parameters: tuple[Any, ...],
    index: int,
    description: str,
) -> sqlite3.Row:
    try:
        rows = connection.execute(query, parameters).fetchmany(2)
    except sqlite3.Error as exc:
        raise TraceLoomAdapterError(
            f"supported link {index} cannot query {description}: {exc}"
        ) from exc
    if not rows:
        raise TraceLoomAdapterError(
            f"supported link {index} references an unknown {description}"
        )
    if len(rows) != 1:
        raise TraceLoomAdapterError(
            f"supported link {index} references an ambiguous {description}"
        )
    return rows[0]


def _lineage_row(row: sqlite3.Row, role: str) -> dict[str, Any]:
    try:
        source_table = row["source_table"]
        source_key = row["source_key"]
    except (IndexError, KeyError) as exc:
        raise TraceLoomAdapterError(
            "TraceLoom lineage row lacks source identity"
        ) from exc
    if (
        not isinstance(source_table, str)
        or not source_table
        or not isinstance(source_key, str)
        or not source_key
        or not isinstance(role, str)
        or not role
    ):
        raise TraceLoomAdapterError("TraceLoom lineage identity is malformed")
    return {
        "source_table": source_table,
        "source_key": source_key,
        "source_role": role,
    }


def _deduplicate_lineage(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    result: list[dict[str, Any]] = []
    for row in rows:
        identity = (row["source_table"], row["source_key"], row["source_role"])
        if identity not in seen:
            seen.add(identity)
            result.append(row)
    return result


def _connect_read_only(database: Path) -> sqlite3.Connection:
    if not isinstance(database, Path):
        raise TraceLoomAdapterError("TraceLoom database path must be a pathlib.Path")
    if not database.is_file():
        raise TraceLoomAdapterError(f"TraceLoom database does not exist: {database}")
    try:
        return sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise TraceLoomAdapterError(
            f"cannot open TraceLoom database: {database}: {exc}"
        ) from exc
