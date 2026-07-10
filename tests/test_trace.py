from vllm_request_lifecycle_profiler.trace import BottleneckKind
from vllm_request_lifecycle_profiler.trace import LifecycleStage
from vllm_request_lifecycle_profiler.trace import TraceEvent
from vllm_request_lifecycle_profiler.trace import attribute_bottleneck
from vllm_request_lifecycle_profiler.trace import compute_spans


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

