"""Pure-ASGI request-ID middleware: accepts a sane X-Request-ID or generates one."""

from __future__ import annotations

import re

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from aqta.core.ids import new_id

HEADER = "x-request-id"
_VALID = re.compile(r"^[A-Za-z0-9._\-]{1,64}$")


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope.get("headers") or []).get(HEADER.encode(), b"").decode("latin-1")
        request_id = incoming if _VALID.match(incoming) else new_id("req")
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((HEADER.encode(), request_id.encode()))
                message["headers"] = headers
            await send(message)

        with structlog.contextvars.bound_contextvars(request_id=request_id):
            await self.app(scope, receive, send_with_id)
