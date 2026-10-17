"""ASGI middleware enforcing a maximum HTTP request-body size.

The limit applies to *every* request regardless of content type (JSON,
multipart, plain text, ...) and cannot be bypassed by omitting the
``Content-Length`` header (chunked transfer): bodies without a declared
length are read with a hard byte cap before being replayed to the inner
application. Oversized requests are rejected with ``413`` and the body is
never handed to the application.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

# Methods that may carry a request body. GET/HEAD/OPTIONS without a declared
# Content-Length are passed straight through so the middleware can never block
# a body-less request waiting for bytes that will never arrive.
_BODY_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _content_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", ()):
        if name == b"content-length":
            try:
                length = int(value)
            except ValueError:
                return None
            return length if length >= 0 else None
    return None


async def _send_413(send: Send, limit: int) -> None:
    body = json.dumps(
        {
            "detail": f"request body exceeds the configured maximum of {limit} bytes",
            "limit": limit,
        }
    ).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class BodySizeLimitMiddleware:
    """Reject requests whose body exceeds ``max_bytes`` with HTTP 413."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = _content_length(scope)
        if declared is not None and declared > self.max_bytes:
            # Known-oversized: refuse before reading a single body byte.
            await _send_413(send, self.max_bytes)
            return

        if declared is not None or scope.get("method") not in _BODY_METHODS:
            # A declared length at or below the limit is safe: the HTTP layer
            # (uvicorn/h11) delivers exactly that many bytes and no more.
            # Body-less methods need no guarding either.
            await self.app(scope, receive, send)
            return

        # No Content-Length (chunked transfer or absent body): read the stream
        # with a hard cap so a streaming client cannot bypass the limit, then
        # replay the buffered body to the inner application unchanged.
        body = b""
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                break
            body += message.get("body", b"")
            if len(body) > self.max_bytes:
                await _send_413(send, self.max_bytes)
                return
            if not message.get("more_body", False):
                break

        consumed = False

        async def replay() -> MutableMapping[str, Any]:
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
