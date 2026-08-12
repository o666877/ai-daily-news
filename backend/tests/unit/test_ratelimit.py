"""Unit tests for app/infra/ratelimit.py.

Covers:
- _user_or_ip_key: returns user:sub if user in context, else ip:remote
- read_limiter / write_limiter Limiter instances exist with correct config
- configure_rate_limits attaches limiter state to app
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from slowapi import Limiter

from app.infra.context import set_user
from app.infra.ratelimit import (
    _user_or_ip_key,
    configure_rate_limits,
    read_limiter,
    write_limiter,
)


def test_read_limiter_is_limiter_instance():
    assert isinstance(read_limiter, Limiter)


def test_write_limiter_is_limiter_instance():
    assert isinstance(write_limiter, Limiter)


def test_user_or_ip_key_no_user_uses_ip():
    """Without user in context, key includes 'ip:' prefix."""
    set_user(None)
    # Provide a fake remote address via patch
    with patch("app.infra.ratelimit.get_remote_address", return_value="127.0.0.1"):
        key = _user_or_ip_key()
    assert key == "ip:127.0.0.1"


def test_user_or_ip_key_with_user():
    """With user in context, key includes 'user:<sub>'."""
    set_user({"sub": "test-user"})
    key = _user_or_ip_key()
    assert key == "user:test-user"
    set_user(None)


def test_user_or_ip_key_user_dict_without_sub_falls_back_to_ip():
    """User dict without 'sub' key → fall back to ip."""
    set_user({"role": "owner"})
    with patch("app.infra.ratelimit.get_remote_address", return_value="10.0.0.1"):
        key = _user_or_ip_key()
    assert key == "ip:10.0.0.1"
    set_user(None)


def test_configure_rate_limits_attaches_state():
    """configure_rate_limits sets limiter state on the FastAPI app."""
    app = FastAPI()
    configure_rate_limits(app)
    assert app.state.read_limiter is read_limiter
    assert app.state.write_limiter is write_limiter


@pytest.mark.asyncio
async def test_ratelimit_handler_raises_rate_limit_error():
    """ratelimit_handler raises RateLimitError → 1006 in error response."""
    from app.infra.errors import RateLimitError
    from app.infra.ratelimit import ratelimit_handler

    # Build a fake RateLimitExceeded with valid limit.
    from slowapi.errors import RateLimitExceeded
    from slowapi.wrappers import Limit

    fake_limit = MagicMock()
    fake_limit.error_message = "rate exceeded"
    exc = RateLimitExceeded(limit=fake_limit)

    with pytest.raises(RateLimitError):
        await ratelimit_handler(MagicMock(), exc)


__all__ = []