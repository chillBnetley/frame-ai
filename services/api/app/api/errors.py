from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import AppError
from app.models.schemas import error_content

logger = logging.getLogger("frame_ai.errors")

_STATUS_CODES = {
    400: "bad_request",
    404: "not_found",
    405: "method_not_allowed",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
    502: "provider_unavailable",
    503: "service_unavailable",
}


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "-")


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_content(exc.code, exc.message, exc.details),
            headers=exc.headers or None,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details: list[dict[str, Any]] = []
        for error in exc.errors():
            context = error.get("ctx") or {}
            limit = {
                key: context[key]
                for key in ("ge", "gt", "le", "lt", "max_length", "min_length")
                if key in context
            }
            details.append(
                {
                    "field": ".".join(str(part) for part in error.get("loc", []) if part != "body"),
                    "rule": error.get("type", "value_error"),
                    "limit": limit,
                    "message": error.get("msg", "Invalid value."),
                }
            )
        return JSONResponse(
            status_code=422,
            content=error_content(
                "validation_error",
                "Request validation failed.",
                {"fields": details},
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_CODES.get(exc.status_code, "http_error")
        message = (
            exc.detail if isinstance(exc.detail, str) else "The request could not be completed."
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=error_content(code, message),
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "unhandled_error request_id=%s method=%s path=%s",
            _request_id(request),
            request.method,
            request.url.path,
        )
        return JSONResponse(
            status_code=500,
            content=error_content("internal_error", "An unexpected error occurred."),
            headers={"X-Request-ID": _request_id(request)},
        )
