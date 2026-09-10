from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path

import pytest

from vllm_request_lifecycle_profiler.blind_attribution import (
    BOOTSTRAP_SEED,
    VIEW_NAMES,
    CaseValidationError,
    calibrate_noise_floor,
    load_candidate_ids,
    load_case_bundle,
    render_comparison_views,
    score_case,
    timed_score_case,
    validate_case_bundle,
    write_locked_method_result,
    write_locked_result,
)

ROOT = Path(__file__).resolve().parents[1]
VOCABULARY = ROOT / "docs" / "blind_attribution_candidate_vocabulary.json"
DEVELOPMENT_CASE = (
    ROOT / "data" / "fixtures" / "blind_attribution_development_case.json"
)


@pytest.fixture
def candidates() -> tuple[str, ...]:
    return load_candidate_ids(VOCABULARY)


@pytest.fixture
def bundle(candidates: tuple[str, ...]) -> dict:
    return load_case_bundle(DEVELOPMENT_CASE, candidate_ids=candidates)


def test_development_bundle_is_closed_and_oracle_free(bundle, candidates):
    validate_case_bundle(bundle, candidate_ids=candidates)
    serialized = json.dumps(bundle).lower()
    assert "ground_truth" not in serialized
    assert '"oracle"' not in serialized
    assert "fault_name" not in serialized


def test_answer_bearing_and_unknown_fields_are_rejected(bundle, candidates):
    leaked = copy.deepcopy(bundle)
    leaked["oracle"] = "queue_or_admission"
    with pytest.raises(CaseValidationError, match="answer-bearing"):
        validate_case_bundle(leaked, candidate_ids=candidates)

    unknown = copy.deepcopy(bundle)
    unknown["pairs"][0]["baseline"]["guess"] = "queue_or_admission"
    with pytest.raises(CaseValidationError, match="unknown keys"):
        validate_case_bundle(unknown, candidate_ids=candidates)

    wrong_owner = copy.deepcopy(bundle)
    wrong_owner["pairs"][0]["baseline"]["normalized_events"][0]["component"] = (
        "frontend"
    )
    with pytest.raises(CaseValidationError, match="ownership mismatch"):
        validate_case_bundle(wrong_owner, candidate_ids=candidates)


def test_unmatched_pair_is_rejected(bundle, candidates):
    unmatched = copy.deepcopy(bundle)
    unmatched["pairs"][0]["treatment"]["configuration_id"] = "different"
    with pytest.raises(CaseValidationError, match="unmatched configuration"):
        validate_case_bundle(unmatched, candidate_ids=candidates)

    unmatched_clock = copy.deepcopy(bundle)
    unmatched_clock["pairs"][0]["treatment"]["clock_model_id"] = "different"
    with pytest.raises(CaseValidationError, match="unmatched clock_model"):
        validate_case_bundle(unmatched_clock, candidate_ids=candidates)

    empty = copy.deepcopy(bundle)
    empty["pairs"][0]["baseline"]["normalized_events"] = []
    empty["pairs"][0]["baseline"]["lifecycle_spans"] = []
    empty["pairs"][0]["baseline"]["lifecycle_edges"] = []
    with pytest.raises(CaseValidationError, match="must contain normalized events"):
        validate_case_bundle(empty, candidate_ids=candidates)


def test_pilot_requires_five_alternating_pairs(bundle, candidates):
    short = copy.deepcopy(bundle)
    short["pairs"].pop()
    with pytest.raises(CaseValidationError, match="5-4096"):
        validate_case_bundle(short, candidate_ids=candidates)

    extended = copy.deepcopy(bundle)
    sixth = _replace_string_values(extended["pairs"][-1], "05", "06")
    sixth["order"] = "BA"
    extended["pairs"].append(sixth)
    validate_case_bundle(extended, candidate_ids=candidates)

    non_alternating = copy.deepcopy(bundle)
    non_alternating["pairs"][1]["order"] = "AB"
    with pytest.raises(CaseValidationError, match="must alternate"):
        validate_case_bundle(non_alternating, candidate_ids=candidates)


def test_cycles_and_overlap_double_charging_are_rejected(bundle, candidates):
    cyclic = copy.deepcopy(bundle)
    observation = cyclic["pairs"][0]["baseline"]
    observation["lifecycle_edges"].append(
        {
            "source_span_id": "s-01-a-dispatch",
            "target_span_id": "s-01-a",
            "kind": "request_handoff",
        }
    )
    with pytest.raises(CaseValidationError, match="contain a cycle"):
        validate_case_bundle(cyclic, candidate_ids=candidates)

    double_charged = copy.deepcopy(bundle)
    observation = double_charged["pairs"][0]["baseline"]
    second = copy.deepcopy(observation["lifecycle_spans"][0])
    second["span_id"] = "s-01-a-overlap"
    observation["lifecycle_spans"].append(second)
    with pytest.raises(CaseValidationError, match="double-charge"):
        validate_case_bundle(double_charged, candidate_ids=candidates)


def test_edges_cannot_cross_request_identity_or_duplicate(bundle, candidates):
    crossed = copy.deepcopy(bundle)
    observation = crossed["pairs"][0]["baseline"]
    foreign_span = copy.deepcopy(observation["lifecycle_spans"][1])
    foreign_span["span_id"] = "foreign-span"
    foreign_span["start_event_id"] = "foreign-start"
    foreign_span["end_event_id"] = "foreign-end"
    foreign_span["trace_id"] = "foreign-trace"
    foreign_span["engine_lifecycle_id"] = "foreign-lifecycle"
    foreign_span["request_id"] = "foreign-request"
    foreign_events = []
    for event_id, original in zip(
        ("foreign-start", "foreign-end"),
        observation["normalized_events"][1:],
        strict=True,
    ):
        event = copy.deepcopy(original)
        event["event_id"] = event_id
        event["trace_id"] = "foreign-trace"
        event["engine_lifecycle_id"] = "foreign-lifecycle"
        event["request_id"] = "foreign-request"
        foreign_events.append(event)
    observation["normalized_events"].extend(foreign_events)
    observation["lifecycle_spans"].append(foreign_span)
    observation["lifecycle_edges"][0]["target_span_id"] = "foreign-span"
    with pytest.raises(CaseValidationError, match="crosses request/lifecycle"):
        validate_case_bundle(crossed, candidate_ids=candidates)

    duplicated = copy.deepcopy(bundle)
    observation = duplicated["pairs"][0]["baseline"]
    observation["lifecycle_edges"].append(
        copy.deepcopy(observation["lifecycle_edges"][0])
    )
    with pytest.raises(CaseValidationError, match="duplicates an existing edge"):
        validate_case_bundle(duplicated, candidate_ids=candidates)


def test_device_backed_span_requires_explicit_traceloom_link(bundle, candidates):
    device_backed = copy.deepcopy(bundle)
    observation = device_backed["pairs"][0]["baseline"]
    for span in observation["lifecycle_spans"]:
        span["clock_domain"] = "device"
    for event in observation["normalized_events"]:
        event["clock_domain"] = "device"
    with pytest.raises(CaseValidationError, match="TraceLoom drill-down link"):
        validate_case_bundle(device_backed, candidate_ids=candidates)


def test_five_views_are_deterministic_and_have_distinct_information(bundle):
    first = render_comparison_views(bundle)
    second = render_comparison_views(bundle)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert tuple(first) == VIEW_NAMES

    aggregate = first["aggregate_metrics"]["pairs"][0]["baseline"]
    assert "metrics" in aggregate and "spans" not in aggregate
    flat = first["flat_stage_timers"]["pairs"][0]["baseline"]
    assert flat["stage_timers_ms"] == {
        "queue_or_admission": 10.0,
        "scheduler_dispatch": 5.0,
    }
    raw = first["raw_normalized_events"]["pairs"][0]["baseline"]
    assert "events" in raw and "edges" not in raw
    assert raw["events"] != bundle["pairs"][0]["baseline"]["lifecycle_spans"]
    assert raw["events"][0]["event_name"] == "queued"
    spans = first["lifecycle_spans_without_causal_ranking"]["pairs"][0]["baseline"]
    assert "spans" in spans and "traceloom_links" not in spans
    dag = first["full_lifecycle_dag"]["pairs"][0]["baseline"]
    assert {"spans", "edges", "traceloom_links"} <= set(dag)


def test_noise_floor_uses_five_pair_nearest_rank_p95():
    calibration = calibrate_noise_floor([1.0, -2.0, 4.0, 3.0, 2.5])
    assert calibration == {
        "null_delta_p95_ms": 4.0,
        "insufficient_evidence_floor_ms": 5.0,
    }
    with pytest.raises(ValueError, match="exactly five"):
        calibrate_noise_floor([1.0] * 4)


def test_scorer_applies_fixed_pairing_bootstrap_and_dominance(bundle, candidates):
    result = score_case(
        bundle,
        candidate_ids=candidates,
        insufficient_evidence_floor_ms=5.0,
        bootstrap_seed=BOOTSTRAP_SEED,
        bootstrap_resamples=10_000,
    )
    assert result.m0_status == "NOT_M0_PROVEN"
    assert not result.abstained
    assert result.top1 == "queue_or_admission"
    assert result.top3 == ("queue_or_admission", "scheduler_dispatch")
    assert result.dominance_score == pytest.approx(20 / 22)
    assert result.confidence_score == pytest.approx(20 / 22)
    assert result.unexplained_residual_share == pytest.approx(2 / 22)
    assert result.candidates[0].paired_deltas_ms == (20.0, 21.0, 19.0, 22.0, 20.0)
    assert result.candidates[0].median_delta_ms == 20.0
    assert result.candidates[0].bootstrap_ci95_ms[0] > 0
    assert result.candidates[0].span_count == 10
    assert result.candidates[0].owners == ("scheduler",)
    assert result.candidates[0].edge_kinds == ("request_handoff",)
    assert result.proposed_counterfactual == {
        "candidate_id": "queue_or_admission",
        "constraint": "change_only_predicted_mechanism",
    }


def test_scorer_fails_closed_on_incomplete_evidence(bundle, candidates):
    incomplete = copy.deepcopy(bundle)
    incomplete["pairs"][2]["treatment"]["evidence_status"]["clock_ambiguous"] = True
    result = score_case(
        incomplete,
        candidate_ids=candidates,
        insufficient_evidence_floor_ms=5.0,
    )
    assert result.abstained
    assert result.top1 is None
    assert "clock_ambiguity" in result.abstain_reasons
    assert not result.input_complete


def test_locked_result_cannot_be_overwritten(tmp_path):
    destination = tmp_path / "locked.json"
    write_locked_result(destination, {"result": "first"})
    assert json.loads(destination.read_text()) == {"result": "first"}
    with pytest.raises(FileExistsError):
        write_locked_result(destination, {"result": "second"})
    assert json.loads(destination.read_text()) == {"result": "first"}


def test_timed_method_result_is_complete_and_locked(tmp_path, bundle, candidates):
    payload = timed_score_case(
        bundle,
        method="full_lifecycle_dag",
        candidate_ids=candidates,
        insufficient_evidence_floor_ms=5.0,
    )
    destination = tmp_path / "method.json"
    write_locked_method_result(destination, payload, candidate_ids=candidates)
    written = json.loads(destination.read_text())
    assert written["method"] == "full_lifecycle_dag"
    assert written["bootstrap_seed"] == BOOTSTRAP_SEED
    assert written["time_to_localize_ms"] >= 0
    with pytest.raises(FileExistsError):
        write_locked_method_result(destination, payload, candidate_ids=candidates)


def test_inconsistent_method_result_is_rejected(tmp_path, bundle, candidates):
    payload = timed_score_case(
        bundle,
        method="full_lifecycle_dag",
        candidate_ids=candidates,
        insufficient_evidence_floor_ms=5.0,
    )
    payload["unexplained_residual_share"] = 0.5
    with pytest.raises(CaseValidationError, match="must sum to one"):
        write_locked_method_result(
            tmp_path / "invalid.json", payload, candidate_ids=candidates
        )
    assert not (tmp_path / "invalid.json").exists()


def test_automated_scorer_cannot_be_mislabeled(bundle, candidates):
    with pytest.raises(ValueError, match="only label full_lifecycle_dag"):
        timed_score_case(
            bundle,
            method="aggregate_metrics",
            candidate_ids=candidates,
            insufficient_evidence_floor_ms=5.0,
        )


def test_unverified_traceloom_evidence_forces_abstention(bundle, candidates):
    linked = copy.deepcopy(bundle)
    observation = linked["pairs"][0]["baseline"]
    span = observation["lifecycle_spans"][0]
    observation["traceloom_links"].append(
        {
            "span_id": span["span_id"],
            "trace_id": span["trace_id"],
            "engine_lifecycle_id": span["engine_lifecycle_id"],
            "recovery_epoch": span["recovery_epoch"],
            "request_id": span["request_id"],
            "event_id": "event-1",
            "link_kind": "execution_support",
            "owner": span["owner"],
            "clock_domain": span["clock_domain"],
            "evidence_source": "traceloom_sqlite",
            "support_state": "supported_exact",
        }
    )
    result = score_case(
        linked,
        candidate_ids=candidates,
        insufficient_evidence_floor_ms=5.0,
    )
    assert result.abstained
    assert "traceloom_evidence_not_verified" in result.abstain_reasons


def test_device_evidence_is_checked_against_traceloom_occurrence(
    tmp_path, bundle, candidates
):
    linked = copy.deepcopy(bundle)
    observation = linked["pairs"][0]["baseline"]
    device_span = observation["lifecycle_spans"][0]
    device_span.update(
        {"clock_domain": "device", "batch_id": "batch-1", "step_id": "step-1"}
    )
    for event in observation["normalized_events"][:2]:
        event.update(
            {
                "clock_domain": "device",
                "batch_id": "batch-1",
                "step_id": "step-1",
            }
        )
    host_boundary = copy.deepcopy(observation["normalized_events"][1])
    host_boundary.pop("batch_id")
    host_boundary.pop("step_id")
    host_boundary["event_id"] = "e-01-a-1-host"
    host_boundary["clock_domain"] = "host-monotonic"
    observation["normalized_events"].append(host_boundary)
    observation["lifecycle_spans"][1]["start_event_id"] = host_boundary["event_id"]
    observation["traceloom_links"].append(
        {
            "span_id": device_span["span_id"],
            "trace_id": device_span["trace_id"],
            "engine_lifecycle_id": device_span["engine_lifecycle_id"],
            "recovery_epoch": device_span["recovery_epoch"],
            "request_id": device_span["request_id"],
            "batch_id": "batch-1",
            "step_id": "step-1",
            "tree_id": "tree-1",
            "node_id": "node-1",
            "occurrence_idx": 0,
            "anchor_id": "anchor-1",
            "event_id": "traceloom-event-1",
            "link_kind": "execution_support",
            "owner": device_span["owner"],
            "clock_domain": "device",
            "evidence_source": "traceloom_sqlite",
            "support_state": "supported_exact",
        }
    )
    database = _traceloom_database(tmp_path / "trace.db", total_us=10_000.0)
    result = score_case(
        linked,
        candidate_ids=candidates,
        insufficient_evidence_floor_ms=5.0,
        traceloom_databases={observation["run_id"]: database},
    )
    assert not result.abstained
    assert result.candidates[0].traceloom_link_count == 1

    mismatched_database = _traceloom_database(
        tmp_path / "trace-mismatch.db", total_us=1_000.0
    )
    result = score_case(
        linked,
        candidate_ids=candidates,
        insufficient_evidence_floor_ms=5.0,
        traceloom_databases={observation["run_id"]: mismatched_database},
    )
    assert result.abstained
    assert "traceloom_device_cost_mismatch" in result.abstain_reasons


def test_non_finite_values_and_scorer_rule_changes_are_rejected(bundle, candidates):
    invalid = copy.deepcopy(bundle)
    invalid["pairs"][0]["baseline"]["metrics"]["ttft_ms"] = float("nan")
    with pytest.raises(CaseValidationError, match="must be non-negative"):
        validate_case_bundle(invalid, candidate_ids=candidates)
    with pytest.raises(ValueError, match="fixed at 10000"):
        score_case(
            bundle,
            candidate_ids=candidates,
            insufficient_evidence_floor_ms=5.0,
            bootstrap_resamples=100,
        )


def _replace_string_values(value, old: str, new: str):
    if isinstance(value, dict):
        return {
            key: _replace_string_values(item, old, new) for key, item in value.items()
        }
    if isinstance(value, list):
        return [_replace_string_values(item, old, new) for item in value]
    if isinstance(value, str):
        return value.replace(old, new)
    return value


def _traceloom_database(path: Path, *, total_us: float) -> Path:
    connection = sqlite3.connect(path)
    connection.executescript(
        f"""
        CREATE TABLE traceloom_semantic_tree (tree_id TEXT);
        CREATE TABLE traceloom_semantic_node (node_id TEXT, tree_id TEXT);
        CREATE TABLE traceloom_tree_node_occurrence (
          node_id TEXT, occurrence_idx INTEGER, start_ns INTEGER, end_ns INTEGER,
          total_us REAL, self_us REAL
        );
        CREATE TABLE traceloom_viz_node_anchor (
          node_id TEXT, occurrence_idx INTEGER, anchor_id TEXT
        );
        CREATE TABLE traceloom_anchor (anchor_id TEXT, event_id TEXT);
        CREATE TABLE traceloom_event (
          event_id TEXT, source_table TEXT, source_key TEXT
        );
        CREATE TABLE traceloom_event_source (
          event_id TEXT, source_ordinal INTEGER, source_table TEXT,
          source_key TEXT, source_role TEXT
        );
        INSERT INTO traceloom_semantic_tree VALUES ('tree-1');
        INSERT INTO traceloom_semantic_node VALUES ('node-1', 'tree-1');
        INSERT INTO traceloom_tree_node_occurrence
          VALUES ('node-1', 0, 0, 10000000, {total_us}, {total_us});
        INSERT INTO traceloom_viz_node_anchor VALUES ('node-1', 0, 'anchor-1');
        INSERT INTO traceloom_anchor VALUES ('anchor-1', 'traceloom-event-1');
        INSERT INTO traceloom_event
          VALUES ('traceloom-event-1', 'TASK', 'row-1');
        INSERT INTO traceloom_event_source
          VALUES ('traceloom-event-1', 0, 'TASK', 'row-1', 'raw_event');
        """
    )
    connection.commit()
    connection.close()
    return path
