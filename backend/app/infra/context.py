"""Context variables for request-scoped state (request_id, user)."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

# Per-request ID; set by middleware, read by error handlers + loggers.
_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")

# Per-request authenticated user (None for anonymous reads).
_user_ctx: ContextVar[Any] = ContextVar("user", default=None)


def set_request_id(request_id: str) -> None:
    _request_id_ctx.set(request_id)


def get_request_id() -> str:
    rid = _request_id_ctx.get()
    return rid if rid else "unknown"


def set_user(user: Any) -> None:
    _user_ctx.set(user)


def get_user() -> Any:
    return _user_ctx.get()


__all__ = ["get_request_id", "get_user", "set_request_id", "set_user"]
