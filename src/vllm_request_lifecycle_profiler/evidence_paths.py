"""Separate fresh outputs from source checkouts and immutable evidence inputs."""

from pathlib import Path


def fresh_external_output(path: Path, *, inputs: tuple[Path, ...] = ()) -> Path:
    root = Path(__file__).resolve().parents[2]
    resolved = path.resolve()
    if not path.is_absolute() or resolved.is_relative_to(root):
        raise ValueError("output must be an absolute path outside the source checkout")
    if path.exists() or path.is_symlink():
        raise ValueError(
            "output must be a new directory; existing evidence is immutable"
        )
    if any(
        resolved.is_relative_to(p.resolve()) or p.resolve().is_relative_to(resolved)
        for p in inputs
    ):
        raise ValueError("output must not overlap an input root")
    return resolved
