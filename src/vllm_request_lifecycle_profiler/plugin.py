from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_PATCHED = False


def register_plugin() -> None:
    """Register the plugin.

    This function must be re-entrant because vLLM can load general plugins in
    multiple processes.
    """

    global _PATCHED
    if _PATCHED:
        return

    try:
        from vllm import envs as vllm_envs
    except Exception:
        logger.exception("Failed to import vLLM during plugin registration.")
        return

    # This sample patch deliberately stays narrow. Replace it with a real
    # optimization boundary such as a scheduler method or attention-layer path.
    setattr(vllm_envs, "VLLM_GENERAL_PLUGIN_TEMPLATE_LOADED", True)

    _PATCHED = True
    logger.info("Registered vLLM general plugin template.")