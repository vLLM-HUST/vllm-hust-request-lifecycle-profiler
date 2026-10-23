"""The migrated remaining collection still supplies paper-facing summaries."""
import importlib.util
import os
from pathlib import Path


def test_collection_probe_and_matrix_inputs(tmp_path):
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
    for name, expected in {
        "synthetic_fault": 2,
        "trace_probe": 3,
        "trace_diagnosis": 2,
        "slow_stream_diagnosis": 2,
        "runtime_hook_pair": 2,
        "runtime_concurrency_anomaly": 2,
        "controlled_fault_matrix": 2,
        "decision_impact": 2,
    }.items():
        args = dict(
            repo_root=root,
            output_dir=tmp_path / name,
            table_dir=tmp_path / name / "tables",
        )
        if name == "trace_probe":
            args["figure_dir"] = tmp_path / name / "figures"
        assets = getattr(module, "generate_" + name + "_assets")(**args)
        assert len(assets) == expected, name
        assert all(Path(asset["path"]).is_file() for asset in assets), name
