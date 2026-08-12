"""Unit tests for app/infra/auth.py (Bearer token dependencies).

Covers:
- _extract_token: well-formed, malformed, missing header
- _verify_token: timing-safe equality (positive + negative)
- get_authenticated_user: anonymous OK, invalid token raises, valid token returns user
- require_auth: missing token raises, invalid token raises, valid token returns user
"""

from __future__ import annotations

import pytest

from app.config import reset_settings_cache
from app.infra.auth import (
    _extract_token,
    _verify_token,
    get_authenticated_user,
    require_auth,
)
from app.infra.errors import UnauthorizedError


# ---------- _extract_token ----------

def test_extract_token_well_formed():
    assert _extract_token("Bearer abc123") == "abc123"


def test_extract_token_lowercase_bearer():
    assert _extract_token("bearer xyz") == "xyz"


def test_extract_token_with_extra_whitespace():
    assert _extract_token("Bearer   token-with-space") == "token-with-space"


def test_extract_token_none_header():
    assert _extract_token(None) is None


def test_extract_token_empty_header():
    assert _extract_token("") is None


def test_extract_token_no_scheme():
    assert _extract_token("just-a-token") is None


def test_extract_token_wrong_scheme():
    assert _extract_token("Basic abc") is None


# ---------- _verify_token ----------

def test_verify_token_match():
    assert _verify_token("abc", "abc") is True


def test_verify_token_mismatch():
    assert _verify_token("abc", "xyz") is False


def test_verify_token_empty_provided():
    assert _verify_token("", "abc") is False


def test_verify_token_empty_expected():
    assert _verify_token("abc", "") is False


def test_verify_token_both_empty():
    assert _verify_token("", "") is False


# ---------- get_authenticated_user ----------

@pytest.mark.asyncio
async def test_get_user_anonymous_no_header():
    """No Authorization header → returns None (anonymous reads allowed)."""
    result = await get_authenticated_user(authorization=None)
    assert result is None


@pytest.mark.asyncio
async def test_get_user_malformed_header_raises():
    """Header present but not Bearer → raises 1003."""
    with pytest.raises(UnauthorizedError):
        await get_authenticated_user(authorization="Token foo")


@pytest.mark.asyncio
async def test_get_user_invalid_token_raises():
    """Bearer with wrong token → raises 1003."""
    with pytest.raises(UnauthorizedError):
        await get_authenticated_user(authorization="Bearer wrong-token")


@pytest.mark.asyncio
async def test_get_user_valid_token_returns_user():
    """Bearer with matching token → returns user dict."""
    # conftest sets AIDAILY_BEARER_TOKEN=test-bearer-token
    result = await get_authenticated_user(authorization="Bearer test-bearer-token")
    assert result is not None
    assert result["sub"] == "local-user"
    assert result["role"] == "owner"


# ---------- require_auth ----------

@pytest.mark.asyncio
async def test_require_auth_missing_header_raises():
    """No Authorization header → raises 1003 (strict)."""
    with pytest.raises(UnauthorizedError):
        await require_auth(authorization=None)


@pytest.mark.asyncio
async def test_require_auth_malformed_raises():
    with pytest.raises(UnauthorizedError):
        await require_auth(authorization="NotBearer foo")


@pytest.mark.asyncio
async def test_require_auth_invalid_raises():
    with pytest.raises(UnauthorizedError):
        await require_auth(authorization="Bearer nope")


@pytest.mark.asyncio
async def test_require_auth_valid_returns_user():
    result = await require_auth(authorization="Bearer test-bearer-token")
    assert result["sub"] == "local-user"


# ---------- effective_bearer_token fallback ----------

def test_effective_bearer_token_uses_configured(monkeypatch):
    """If bearer_token is set in env, use it; don't generate."""
    monkeypatch.setenv("AIDAILY_BEARER_TOKEN", "explicit-token")
    reset_settings_cache()
    from app.config import get_settings
    s = get_settings()
    assert s.effective_bearer_token == "explicit-token"


def test_effective_bearer_token_fallback_when_empty(monkeypatch):
    """If empty, fallback generates a stable token."""
    monkeypatch.setenv("AIDAILY_BEARER_TOKEN", "")
    reset_settings_cache()
    from app.config import get_settings
    s = get_settings()
    assert s.effective_bearer_token  # non-empty generated
    # Stable across calls in same process (cached module-level var)
    assert s.effective_bearer_token == s.effective_bearer_token


__all__ = []