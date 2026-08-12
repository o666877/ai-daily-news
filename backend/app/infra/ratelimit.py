"""Rate limiting via slowapi.

Two policies:
- reads: 120/minute per IP (FR-027)
- writes: 30/minute per user (FR-027)

Exceedance raises business code 1006.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.infra.context import get_request_id, get_user
from app.infra.errors import ErrorOut, RateLimitError


def _user_or_ip_key(endpoint: str = "") -> str:
    """Return rate-limit key: user.sub if authed else client IP."""
    user = get_user()
    if user and isinstance(user, dict) and user.get("sub"):
        return f"user:{user['sub']}"
    # Fall back to remote address (set by middleware via context).
    return f"ip:{get_remote_address()}"


# Read limiter: per-IP 120/min.
read_limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])

# Write limiter: per-user 30/min.
write_limiter = Limiter(key_func=_user_or_ip_key, default_limits=["30/minute"])


async def ratelimit_handler(_request, exc: RateLimitExceeded) -> None:
    """Convert slowapi RateLimitExceeded → business 1006."""
    rid = get_request_id()
    from fastapi.responses import JSONResponse

    body = ErrorOut(code=1006, message="操作太频繁，稍后再试", requestId=rid)
    raise RateLimitError()  # let app exception handler format the response


def configure_rate_limits(app) -> None:
    """Attach slowapi state to app (called from main.py)."""
    app.state.read_limiter = read_limiter
    app.state.write_limiter = write_limiter


__all__ = [
    "configure_rate_limits",
    "ratelimit_handler",
    "read_limiter",
    "write_limiter",
]
