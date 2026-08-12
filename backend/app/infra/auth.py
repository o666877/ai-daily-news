"""Bearer auth dependency.

- Reads anonymous by default.
- `require_auth` for write endpoints (Settings/Share) — raises 1003 if no token.
- Uses `secrets.compare_digest` to prevent timing attacks.
"""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import Header

from app.config import get_settings
from app.infra.context import set_user
from app.infra.errors import UnauthorizedError


def _extract_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


def _verify_token(provided: str | None, expected: str) -> bool:
    if not provided or not expected:
        return False
    return secrets.compare_digest(provided, expected)


async def get_authenticated_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any] | None:
    """Read-only dependency: returns user dict if token valid, None if anonymous.

    Raises UnauthorizedError ONLY if a malformed/invalid Authorization header
    was explicitly sent (so anonymous reads still work).
    """
    settings = get_settings()
    expected = settings.effective_bearer_token
    provided = _extract_token(authorization)
    if authorization is None:
        # Anonymous — fine for reads.
        return None
    if provided is None:
        raise UnauthorizedError("Authorization 头格式错误")
    if not _verify_token(provided, expected):
        raise UnauthorizedError("token 失效")
    user = {"sub": "local-user", "role": "owner"}
    set_user(user)
    return user


async def require_auth(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
    """Strict dependency: write endpoints. 403 if no/invalid token."""
    settings = get_settings()
    expected = settings.effective_bearer_token
    provided = _extract_token(authorization)
    if provided is None:
        raise UnauthorizedError("缺少 Authorization Bearer 头")
    if not _verify_token(provided, expected):
        raise UnauthorizedError("token 失效")
    user = {"sub": "local-user", "role": "owner"}
    set_user(user)
    return user


__all__ = ["get_authenticated_user", "require_auth"]
