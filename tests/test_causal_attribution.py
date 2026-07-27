from pathlib import Path

from vllm_request_lifecycle_profiler.causal_attribution import (
    evaluate_intervention_fixture,
)
from vllm_request_lifecycle_profiler.causal_attribution import (
    load_intervention_fixture,
)


FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "fixtures"
    / "intervention_linked_lifecycle.json"
)


def test_intervention_pair_supports_only_offline_fixture_causality() -> None:
    report = evaluate_intervention_fixture(load_intervention_fixture(FIXTURE))
    pair = report["rows"][0]

    assert pair["dominant_span_localization"]["span"] == "decode"
    assert pair["causal_evidence"]["status"] == "intervention_supported_offline_fixture"
    assert pair["causal_evidence"]["supported"] is True
    assert pair["causal_evidence"]["span_deltas_ms"]["decode"] == 50.0
    assert report["m0_status"] == "NOT_M0_PROVEN"


def test_dominant_span_without_intervention_remains_localization_only() -> None:
    report = evaluate_intervention_fixture(load_intervention_fixture(FIXTURE))
    observation = report["rows"][1]

    assert observation["dominant_span_localization"]["span"] == "prefill"
    assert observation["causal_evidence"] == {
        "status": "localization_only",
        "supported": False,
        "reason": "matched_control_and_intervention_required",
    }


def test_unintended_second_span_change_breaks_causal_support() -> None:
    fixture = load_intervention_fixture(FIXTURE)
    fixture["cases"][0]["observed_durations_ms"]["queueing"] += 7.0

    report = evaluate_intervention_fixture(fixture)
    causal = report["rows"][0]["causal_evidence"]

    assert causal["status"] == "intervention_not_supported"
    assert causal["non_target_spans_unchanged"] is False
