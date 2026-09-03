"""Loopback-only control middleware for the Issue #19 real-path experiment.

The middleware is not installed by the profiler plugin.  The M0 runner must
explicitly pass it to ``vllm serve --middleware``.  It exposes only the two
operations needed by the preregistered experiment: a bounded state snapshot
and repeated calls to the concrete AsyncLLM internal-abort path.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

CONTROL_PREFIX = "/__issue19"
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})


def _observer_snapshot() -> dict[str, Any]:
    try:
        from vllm_request_lifecycle_profiler.plugin import get_lifecycle_observer

        observer = get_lifecycle_observer()
        if observer is None:
            return {"available": False}
        snapshot = getattr(observer, "snapshot", None)
        if callable(snapshot):
            return {"available": True, **snapshot()}
        return {"available": True}
    except Exception as exc:  # noqa: BLE001 - control evidence fails closed.
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}


def _engine_snapshot(engine: object) -> dict[str, Any]:
    processor = getattr(engine, "output_processor", None)
    states = getattr(processor, "request_states", {})
    external = getattr(processor, "external_req_ids", {})
    return {
        "active_internal_request_ids": sorted(str(key) for key in states),
        "external_request_ids": {
            str(key): sorted(str(value) for value in values)
            for key, values in external.items()
        },
    }


def _client_is_loopback(request: Request) -> bool:
    return request.client is not None and request.client.host in _LOOPBACK_HOSTS


async def _read_json_object(request: Request) -> Mapping[str, Any] | None:
    try:
        value = await request.json()
    except Exception:  # noqa: BLE001 - malformed control request fails closed.
        return None
    return value if isinstance(value, Mapping) else None


async def issue19_control_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Intercept the explicit Issue #19 control namespace on loopback only."""

    if not request.url.path.startswith(CONTROL_PREFIX):
        return await call_next(request)
    if not _client_is_loopback(request):
        return JSONResponse({"error": "loopback_only"}, status_code=403)

    engine = getattr(request.app.state, "engine_client", None)
    if engine is None:
        return JSONResponse({"error": "engine_unavailable"}, status_code=503)

    if request.url.path == f"{CONTROL_PREFIX}/state" and request.method == "GET":
        return JSONResponse(
            {
                "schema_version": "issue19-control-state/v1",
                "engine": _engine_snapshot(engine),
                "observer": _observer_snapshot(),
            }
        )

    if (
        request.url.path == f"{CONTROL_PREFIX}/duplicate-abort"
        and request.method == "POST"
    ):
        body = await _read_json_object(request)
        request_id = body.get("internal_request_id") if body is not None else None
        attempts = body.get("attempts") if body is not None else None
        if not isinstance(request_id, str) or not request_id:
            return JSONResponse(
                {"error": "invalid_internal_request_id"}, status_code=400
            )
        if attempts != 2:
            return JSONResponse({"error": "attempts_must_equal_two"}, status_code=400)
        abort = getattr(engine, "abort", None)
        if not callable(abort):
            return JSONResponse(
                {"error": "async_llm_abort_unavailable"}, status_code=409
            )
        try:
            await abort(request_id, internal=True, terminal_cause="explicit_cancel")
            await abort(request_id, internal=True, terminal_cause="explicit_cancel")
        except TypeError as exc:
            return JSONResponse(
                {"error": "internal_abort_signature_unavailable", "detail": str(exc)},
                status_code=409,
            )
        return JSONResponse(
            {
                "schema_version": "issue19-duplicate-abort/v1",
                "internal_request_id": request_id,
                "attempts": 2,
            }
        )

    return JSONResponse({"error": "unknown_control_operation"}, status_code=404)


__all__ = ["CONTROL_PREFIX", "issue19_control_middleware"]
