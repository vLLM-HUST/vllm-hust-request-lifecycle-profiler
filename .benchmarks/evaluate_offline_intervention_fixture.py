from __future__ import annotations

import argparse
import json
from pathlib import Path

from vllm_request_lifecycle_profiler.causal_attribution import (
    evaluate_intervention_fixture,
)
from vllm_request_lifecycle_profiler.causal_attribution import (
    load_intervention_fixture,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate an offline intervention-linked trace fixture.")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/fixtures/intervention_linked_lifecycle.json"),
    )
    args = parser.parse_args()
    report = evaluate_intervention_fixture(load_intervention_fixture(args.input))
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
