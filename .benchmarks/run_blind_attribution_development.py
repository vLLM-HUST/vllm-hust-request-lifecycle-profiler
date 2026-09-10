"""Exercise the blind-attribution pipeline on a public development fixture."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from vllm_request_lifecycle_profiler.blind_attribution import (
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    load_candidate_ids,
    load_case_bundle,
    render_comparison_views,
    timed_score_case,
    write_locked_method_result,
    write_locked_result,
)

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--case",
        type=Path,
        default=ROOT / "data" / "fixtures" / "blind_attribution_development_case.json",
    )
    parser.add_argument(
        "--vocabulary",
        type=Path,
        default=ROOT / "docs" / "blind_attribution_candidate_vocabulary.json",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--noise-floor-ms", type=float, default=5.0)
    args = parser.parse_args()

    candidates = load_candidate_ids(args.vocabulary)
    bundle = load_case_bundle(args.case, candidate_ids=candidates)
    views = render_comparison_views(bundle)
    for method, view in views.items():
        write_locked_result(args.output / "views" / f"{method}.json", view)
    result = timed_score_case(
        bundle,
        method="full_lifecycle_dag",
        candidate_ids=candidates,
        insufficient_evidence_floor_ms=args.noise_floor_ms,
        bootstrap_seed=BOOTSTRAP_SEED,
        bootstrap_resamples=BOOTSTRAP_RESAMPLES,
    )
    write_locked_method_result(
        args.output / "full_lifecycle_dag_result.json",
        result,
        candidate_ids=candidates,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
