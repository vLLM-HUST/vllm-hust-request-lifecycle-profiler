from vllm_request_lifecycle_profiler.trace import BottleneckKind
from vllm_request_lifecycle_profiler.trace import LifecycleStage
from vllm_request_lifecycle_profiler.trace import TraceEvent
from vllm_request_lifecycle_profiler.trace import attribute_bottleneck
from vllm_request_lifecycle_profiler.trace import compute_spans
from vllm_request_lifecycle_profiler.trace import evaluate_fault_injection_matrix
from vllm_request_lifecycle_profiler.trace import evaluate_schema_coverage
from vllm_request_lifecycle_profiler.trace import synthetic_fault_scenarios


def _event(stage, timestamp):
    return TraceEvent("req-1", stage, timestamp)


def test_compute_spans_from_lifecycle_events():
    spans = compute_spans(
        [
            _event(LifecycleStage.RECEIVED, 0),
            _event(LifecycleStage.TOKENIZED, 3),
            _event(LifecycleStage.QUEUED, 4),
            _event(LifecycleStage.SCHEDULED, 10),
            _event(LifecycleStage.FIRST_TOKEN, 30),
        ]
    )
    assert [span.name for span in spans] == [
        "tokenization",
        "queueing",
        "prefill",
    ]
    assert [span.duration_ms for span in spans] == [3, 6, 20]


def test_attributes_largest_complete_span():
    attribution = attribute_bottleneck(
        [
            _event(LifecycleStage.RECEIVED, 0),
            _event(LifecycleStage.TOKENIZED, 2),
            _event(LifecycleStage.QUEUED, 3),
            _event(LifecycleStage.SCHEDULED, 100),
            _event(LifecycleStage.FIRST_TOKEN, 110),
            _event(LifecycleStage.DECODE_DONE, 130),
            _event(LifecycleStage.STREAM_DONE, 135),
        ]
    )
    assert attribution.kind is BottleneckKind.QUEUEING
    assert attribution.duration_ms == 97


def test_unknown_when_no_complete_span_exists():
    attribution = attribute_bottleneck(
        [_event(LifecycleStage.RECEIVED, 0), _event(LifecycleStage.QUEUED, 10)]
    )
    assert attribution.kind is BottleneckKind.UNKNOWN
    assert attribution.reason == "no_complete_lifecycle_span"


def test_schema_coverage_reports_missing_events_and_spans():
    coverage = evaluate_schema_coverage(
        [
            _event(LifecycleStage.RECEIVED, 0),
            _event(LifecycleStage.TOKENIZED, 2),
            _event(LifecycleStage.QUEUED, 3),
        ]
    )
    assert coverage.request_id == "req-1"
    assert coverage.observed_stages == (
        LifecycleStage.RECEIVED,
        LifecycleStage.TOKENIZED,
        LifecycleStage.QUEUED,
    )
    assert LifecycleStage.CLEANUP_DONE in coverage.missing_stages
    assert coverage.complete_span_names == ("tokenization",)
    assert "queueing" in coverage.missing_span_names
    assert coverage.missing_event_rate == 6 / 9


def test_kv_pressure_marker_distinguishes_pressure_from_plain_prefill():
    events = [
        _event(LifecycleStage.RECEIVED, 0),
        _event(LifecycleStage.TOKENIZED, 1),
        _event(LifecycleStage.QUEUED, 2),
        TraceEvent("req-1", LifecycleStage.SCHEDULED, 3, {"kv_pressure": True}),
        TraceEvent("req-1", LifecycleStage.FIRST_TOKEN, 100, {"kv_cache_pressure_ratio": 0.98}),
        _event(LifecycleStage.DECODE_DONE, 110),
        _event(LifecycleStage.STREAM_DONE, 112),
        _event(LifecycleStage.CLEANUP_DONE, 113),
    ]
    attribution = attribute_bottleneck(events)
    assert attribution.kind is BottleneckKind.KV_PRESSURE
    assert attribution.span_name == "prefill"


def test_synthetic_fault_matrix_covers_required_bottleneck_classes():
    matrix = evaluate_fault_injection_matrix(synthetic_fault_scenarios())
    assert matrix.scenario_count == 7
    assert matrix.correct_count == 7
    assert matrix.false_positive_count == 0
    assert matrix.false_negative_count == 0
    assert matrix.accuracy == 1.0
    assert {row["expected"] for row in matrix.rows} == {
        BottleneckKind.TOKENIZATION.value,
        BottleneckKind.QUEUEING.value,
        BottleneckKind.PREFILL.value,
        BottleneckKind.DECODE.value,
        BottleneckKind.KV_PRESSURE.value,
        BottleneckKind.STREAMING.value,
        BottleneckKind.CLEANUP.value,
    }
    assert all(row["missing_event_rate"] == 0.0 for row in matrix.rows)
