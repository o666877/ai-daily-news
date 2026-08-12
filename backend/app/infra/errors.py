"""Unified error handling: business exception classes + FastAPI handlers.

Implements the 11 business codes from contracts/README.md error table:
- 1001 missing parameter        (400)
- 1002 invalid enum             (400)
- 1003 unauthorized             (401)
- 1004 forbidden                (403)
- 1005 validation failed        (422)
- 1006 rate limit               (429)
- 2001 article not found        (404)
- 2002 issue not generated      (404)
- 2003 issue generating         (409)
- 9001 internal error           (500)
- 9002 pipeline busy            (503)
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.infra.context import get_request_id


# ---------------------------------------------------------------------------
# Response schema
# ---------------------------------------------------------------------------


class ErrorOut(BaseModel):
    """Unified error response body: only {code, message, requestId}."""

    code: int
    message: str
    requestId: str


# ---------------------------------------------------------------------------
# Business exception hierarchy
# ---------------------------------------------------------------------------

# HTTP status mapping for each business code.
_CODE_TO_HTTP: dict[int, int] = {
    1001: 400,
    1002: 400,
    1003: 401,
    1004: 403,
    1005: 422,
    1006: 429,
    2001: 404,
    2002: 404,
    2003: 409,
    9001: 500,
    9002: 503,
}


class AppException(Exception):
    """Base business exception. Carries code + message; HTTP status derived."""

    code: int = 9001
    message: str = "服务内部错误"

    def __init__(self, message: str | None = None, *, code: int | None = None) -> None:
        self.message = message if message is not None else self.message
        if code is not None:
            self.code = code
        super().__init__(self.message)

    @property
    def http_status(self) -> int:
        return _CODE_TO_HTTP.get(self.code, 500)


# Convenience subclasses for each code.


class MissingParamError(AppException):
    code = 1001
    message = "缺少必填参数"


class InvalidEnumError(AppException):
    code = 1002
    message = "枚举值非法"


class UnauthorizedError(AppException):
    code = 1003
    message = "未认证或 token 失效"


class ForbiddenError(AppException):
    code = 1004
    message = "无权限"


class ValidationError(AppException):
    code = 1005
    message = "请求体校验失败"


class RateLimitError(AppException):
    code = 1006
    message = "操作太频繁，稍后再试"


class ArticleNotFoundError(AppException):
    code = 2001
    message = "文章不存在"


class IssueNotGeneratedError(AppException):
    code = 2002
    message = "今日刊尚未生成完成"


class IssueGeneratingError(AppException):
    code = 2003
    message = "今日刊正在生成中"


class InternalError(AppException):
    code = 9001
    message = "服务内部错误"


class PipelineBusyError(AppException):
    code = 9002
    message = "采集或摘要管线繁忙"


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _error_response(code: int, message: str, http_status: int) -> JSONResponse:
    """Build a JSONResponse with the unified ErrorOut shape."""
    body = ErrorOut(code=code, message=message, requestId=get_request_id())
    return JSONResponse(status_code=http_status, content=body.model_dump())


async def app_exception_handler(_req: Request, exc: AppException) -> JSONResponse:
    """Handle AppException subclasses."""
    return _error_response(exc.code, exc.message, exc.http_status)


async def validation_exception_handler(
    _req: Request, exc: RequestValidationError
) -> JSONResponse:
    """Map Pydantic validation failures → 1005 (body) or 1002 (query enum).

    Heuristic: errors located in `query` or `path` → enum/param issue (1002);
    errors in `body` → request body validation (1005).
    """
    errors = exc.errors()
    has_query_or_path = any(
        e.get("loc") and e["loc"][0] in ("query", "path") for e in errors
    )
    if has_query_or_path:
        # Bad enum or query param value
        return _error_response(
            1002,
            "枚举值非法或参数错误" if has_query_or_path else "请求参数错误",
            400,
        )
    return _error_response(1005, "请求体校验失败", 422)


async def http_exception_handler(
    _req: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Map Starlette HTTPException to business code by status code."""
    code_by_status = {
        400: 1001,
        401: 1003,
        403: 1004,
        404: 2001,
        409: 2003,
        422: 1005,
        429: 1006,
        500: 9001,
        503: 9002,
    }
    code = code_by_status.get(exc.status_code, 9001)
    message = str(exc.detail) if exc.detail else "服务内部错误"
    return _error_response(code, message, exc.status_code)


async def unhandled_exception_handler(
    _req: Request, exc: Exception
) -> JSONResponse:
    """Catch-all: never leak stack/SQL/secrets — return 9001 only."""
    # Full stack is logged via the logging module (see logging.py).
    import logging

    logging.getLogger("app.errors").exception(
        "Unhandled exception", extra={"exception_type": type(exc).__name__}
    )
    return _error_response(9001, "服务内部错误", 500)


def register_exception_handlers(app: FastAPI) -> None:
    """Wire all exception handlers into the FastAPI app."""
    app.add_exception_handler(AppException, app_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)  # type: ignore[arg-type]


__all__ = [
    "AppException",
    "ArticleNotFoundError",
    "ErrorOut",
    "ForbiddenError",
    "InternalError",
    "InvalidEnumError",
    "IssueGeneratingError",
    "IssueNotGeneratedError",
    "MissingParamError",
    "PipelineBusyError",
    "RateLimitError",
    "UnauthorizedError",
    "ValidationError",
    "register_exception_handlers",
]
