from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from starlette.requests import Request
from starlette.responses import Response

from vllm_request_lifecycle_profiler.issue19_control import (
    issue19_control_middleware,
)


class _Engine:
    def __init__(self) -> None:
        self.abort = AsyncMock()
        self.output_processor = SimpleNamespace(
            request_states={"chatcmpl-one": object()},
            external_req_ids={"one": ["chatcmpl-one"]},
        )


def _request(path: str, engine: object, *, method: str = "GET") -> Request:
    body = b'{"internal_request_id":"chatcmpl-one","attempts":2}'
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [(b"host", b"127.0.0.1")],
        "client": ("127.0.0.1", 1234),
        "server": ("127.0.0.1", 29431),
        "app": SimpleNamespace(state=SimpleNamespace(engine_client=engine)),
    }
    return Request(scope, receive)


def test_duplicate_abort_calls_same_internal_identity_twice() -> None:
    engine = _Engine()

    async def call_next(_: Request) -> Response:
        raise AssertionError("control request must not reach the serving route")

    response = asyncio.run(
        issue19_control_middleware(
            _request("/__issue19/duplicate-abort", engine, method="POST"), call_next
        )
    )

    assert response.status_code == 200
    assert engine.abort.await_count == 2
    assert engine.abort.await_args_list[0] == engine.abort.await_args_list[1]
    engine.abort.assert_awaited_with(
        "chatcmpl-one", internal=True, terminal_cause="explicit_cancel"
    )


def test_state_reports_only_request_identity_and_counts(monkeypatch) -> None:
    engine = _Engine()
    monkeypatch.setattr(
        "vllm_request_lifecycle_profiler.issue19_control._observer_snapshot",
        lambda: {
            "available": True,
            "active_request_ids": ["chatcmpl-one"],
            "abort_attempts": {},
            "resource_observation_count": 0,
        },
    )

    async def call_next(_: Request) -> Response:
        raise AssertionError("control request must not reach the serving route")

    response = asyncio.run(
        issue19_control_middleware(_request("/__issue19/state", engine), call_next)
    )

    assert response.status_code == 200
    assert b"chatcmpl-one" in response.body
    assert b"messages" not in response.body


def test_non_control_path_is_unchanged() -> None:
    engine = _Engine()

    async def call_next(_: Request) -> Response:
        return Response(status_code=204)

    response = asyncio.run(
        issue19_control_middleware(_request("/health", engine), call_next)
    )

    assert response.status_code == 204
