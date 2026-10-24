"""Stage verified historical paper inputs without executing archived code."""

import argparse
import json
import subprocess
from pathlib import Path, PurePosixPath

from fetch_mod_consumer_evidence import digest, fetch

REPOSITORY = Path(__file__).resolve().parents[1]
PREFIX = "paper/request_lifecycle_causal_profiler/"
MANUSCRIPT = "request_lifecycle_causal_profiler.tex"


def stage(root, destination, manifest):
    root, destination = Path(root), Path(destination)
    for path in (root, destination):
        if not path.is_absolute() or path.resolve().is_relative_to(REPOSITORY):
            raise ValueError("Use absolute external evidence and output directories")
    if destination.exists() or destination.resolve().is_relative_to(root.resolve()):
        raise ValueError("Output must be new and separate from the evidence root")
    selected = {}
    for row in manifest["files"]:
        name = row["path"]
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or str(path) != name:
            raise ValueError("Unsafe manifest path")
        if not name.startswith(PREFIX):
            continue
        relative = name[len(PREFIX) :]
        if not (
            relative in (MANUSCRIPT, "references.bib")
            or relative.startswith("tables/generated/")
            and relative.endswith(".tex")
            or relative.startswith("figures/generated/")
            and relative.endswith(".svg")
        ):
            continue
        if relative in selected:
            raise ValueError("Duplicate paper input")
        source = root / name
        if not source.resolve().is_relative_to(root.resolve()) or source.is_symlink():
            raise ValueError("Paper input escapes evidence root")
        raw = source.read_bytes()
        if len(raw) != row["bytes"] or digest(raw) != row["sha256"]:
            raise ValueError("Paper input checksum mismatch")
        selected[relative] = raw
    if MANUSCRIPT not in selected or "references.bib" not in selected:
        raise ValueError("Missing manuscript or bibliography")
    destination.mkdir(parents=True, exist_ok=False)
    for relative, raw in selected.items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--compile", action="store_true")
    args = parser.parse_args()
    config = json.loads((REPOSITORY / "BENCHMARK_RESEARCH.json").read_text())
    raw = fetch(config["manifest_url"], 2_000_000)
    if digest(raw) != config["manifest_sha256"]:
        raise ValueError("Manifest checksum mismatch")
    selected = stage(args.evidence_root, args.output_dir, json.loads(raw))
    print(f"Verified and staged {len(selected)} historical paper inputs")
    if args.compile:
        subprocess.run(
            ["tectonic", "--keep-logs", "--keep-intermediates", MANUSCRIPT],
            cwd=args.output_dir,
            check=True,
        )


if __name__ == "__main__":
    main()
