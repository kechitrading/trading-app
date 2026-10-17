"""Global error handlers: one JSON error shape, no internals leaked."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from aqta.core.errors import AqtaError, AuthError
from aqta.core.logs import get_logger

log = get_logger(__name__)


def _body(request: Request, code: str, message: str) -> dict[str, object]:
    return {
        "error": {"code": code, "message": message},
        "request_id": getattr(request.state, "request_id", None),
    }


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AqtaError)
    async def aqta_error(request: Request, exc: AqtaError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if isinstance(exc, AuthError) else None
        return JSONResponse(
            _body(request, exc.code, str(exc)), status_code=exc.http_status, headers=headers
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            {
                **_body(request, "validation_error", "request validation failed"),
                "details": exc.errors(),
            },
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("api.unhandled_error", path=request.url.path)
        return JSONResponse(_body(request, "internal_error", "internal server error"), 500)
