from __future__ import annotations

import os


def _merge_plugins(existing: str | None, plugin_name: str) -> str:
    if not existing:
        return plugin_name
    parts = [part.strip() for part in existing.split(",") if part.strip()]
    if plugin_name not in parts:
        parts.append(plugin_name)
    return ",".join(parts)


def main() -> None:
    os.environ["VLLM_PLUGINS"] = _merge_plugins(
        os.getenv("VLLM_PLUGINS"),
        "request_lifecycle_profiler",
    )

    from vllm.entrypoints.cli.main import main as vllm_main

    vllm_main()


if __name__ == "__main__":
    main()