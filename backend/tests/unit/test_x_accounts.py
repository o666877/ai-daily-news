"""Unit tests for default X account list + settings x_account_list."""

from __future__ import annotations

from app.config import reset_settings_cache
from app.pipeline.defaults.x_accounts import DEFAULT_X_ACCOUNTS, get_accounts


def test_default_accounts_has_at_least_25():
    """At least ~25 KOLs per T032 description."""
    assert len(DEFAULT_X_ACCOUNTS) >= 20


def test_default_accounts_are_unique():
    assert len(DEFAULT_X_ACCOUNTS) == len(set(DEFAULT_X_ACCOUNTS))


def test_default_accounts_are_non_empty_strings():
    for acc in DEFAULT_X_ACCOUNTS:
        assert isinstance(acc, str)
        assert acc.strip()


def test_get_accounts_with_override():
    """Override CSV parsed."""
    assert get_accounts("a,b,c") == ["a", "b", "c"]


def test_get_accounts_no_override_returns_default():
    assert get_accounts(None) == DEFAULT_X_ACCOUNTS
    assert get_accounts("") == DEFAULT_X_ACCOUNTS


def test_settings_x_account_list_empty_when_unset(monkeypatch):
    monkeypatch.setenv("AIDAILY_X_ACCOUNTS", "")
    reset_settings_cache()
    from app.config import get_settings

    s = get_settings()
    assert s.x_account_list == []


def test_settings_x_account_list_parses_csv(monkeypatch):
    monkeypatch.setenv("AIDAILY_X_ACCOUNTS", "alice, bob ,carol")
    reset_settings_cache()
    from app.config import get_settings

    s = get_settings()
    assert s.x_account_list == ["alice", "bob", "carol"]


def test_settings_x_account_list_filters_empty(monkeypatch):
    """Empty fragments from trailing commas should be removed."""
    monkeypatch.setenv("AIDAILY_X_ACCOUNTS", ",,alice,,")
    reset_settings_cache()
    from app.config import get_settings

    s = get_settings()
    assert s.x_account_list == ["alice"]


__all__ = []