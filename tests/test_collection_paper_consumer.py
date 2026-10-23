"""The migrated remaining collection still supplies paper-facing summaries."""
import importlib.util
import os
from pathlib import Path


def test_collection_probe_and_matrix_inputs():
    repo = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "collection_export", repo / "paper/request_lifecycle_causal_profiler/experiments/export_paper_assets.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = Path(os.environ["BENCHMARK_COLLECTION_ROOT"])
    probe = module._trace_probe_summary(root)
    assert probe["request_count"] == 12
    assert probe["success_count"] == 12
