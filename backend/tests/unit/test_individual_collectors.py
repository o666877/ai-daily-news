"""Unit tests for individual collectors (github, reddit, web, x_rsshub).

Each collector is exercised in isolation with monkeypatched settings +
httpx-mocked or fallback behavior. Network is never touched.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.config import reset_settings_cache
from app.models.article import RawItem
from app.models.meta import SourceKey


# ---------- helpers ----------

def _patch_settings(monkeypatch, **overrides):
    defaults = {
        "AIDAILY_GITHUB_TOKEN": "",
        "AIDAILY_X_RSSHUB_BASE_URL": "",
        "AIDAILY_X_ACCOUNTS": "",
        "AIDAILY_REDDIT_UA": "ai-daily/test",
    }
    for k, v in overrides.items():
        monkeypatch.setenv(k, v)
    reset_settings_cache()


# ---------- GitHub collector ----------

@pytest.mark.asyncio
async def test_collect_github_no_token_returns_empty(monkeypatch, respx_mock):
    """Without token, falls back to trending scrape; respx mock returns empty."""
    _patch_settings(monkeypatch)  # no github_token

    from app.pipeline.collectors.github import collect_github

    # Mock the trending fallback to return empty HTML
    respx_mock.get("https://github.com/trending").respond(200, text="<html></html>")

    items = await collect_github()
    assert items == []


@pytest.mark.asyncio
async def test_collect_github_with_token_uses_api(monkeypatch, respx_mock):
    """With token, calls API and parses repository list."""
    _patch_settings(monkeypatch, AIDAILY_GITHUB_TOKEN="ghp_test")

    from app.pipeline.collectors.github import collect_github

    respx_mock.get("https://api.github.com/search/repositories").respond(
        200,
        json={
            "items": [
                {
                    "full_name": "user/awesome-llm",
                    "description": "An agent framework for autonomous workflows",
                    "stargazers_count": 500,
                    "html_url": "https://github.com/user/awesome-llm",
                    "owner": {"avatar_url": "https://avatars.example.com/u.png"},
                    "created_at": "2026-08-10T00:00:00Z",
                    "updated_at": "2026-08-11T00:00:00Z",
                }
            ]
        },
    )

    items = await collect_github()
    assert len(items) == 1
    assert items[0].sourceKey == SourceKey.GITHUB
    assert "awesome-llm" in items[0].title
    assert "github.com/user/awesome-llm" in items[0].sourceUrl


@pytest.mark.asyncio
async def test_collect_github_api_error_falls_back(monkeypatch, respx_mock):
    """API error → fallback to trending (returns empty)."""
    _patch_settings(monkeypatch, AIDAILY_GITHUB_TOKEN="bad-token")

    from app.pipeline.collectors.github import collect_github

    # API returns 403
    respx_mock.get("https://api.github.com/search/repositories").respond(403, json={})
    # Trending scrape returns empty
    respx_mock.get("https://github.com/trending").respond(200, text="<html></html>")

    items = await collect_github()
    assert items == []


# ---------- Reddit collector ----------

@pytest.mark.asyncio
async def test_collect_reddit_no_praw_returns_empty(monkeypatch):
    """Without praw install or with monkey-patched import failure → empty."""
    _patch_settings(monkeypatch)

    # Patch praw so import succeeds but raises on use
    import builtins

    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "praw":
            raise ImportError("praw not installed")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    from app.pipeline.collectors.reddit import collect_reddit

    items = await collect_reddit()
    assert items == []


@pytest.mark.asyncio
async def test_collect_reddit_success(monkeypatch):
    """Successful subreddit.top() returns RawItems."""
    _patch_settings(monkeypatch)

    from app.pipeline.collectors import reddit as reddit_module

    class _FakeSubmission:
        def __init__(self, title, url, id_):
            self.title = title
            self.url = url
            self.id = id_
            self.permalink = f"/r/test/{id_}"
            self.created_utc = datetime(2026, 8, 12, 8, 0, tzinfo=timezone.utc).timestamp()

    class _FakeSubreddit:
        def top(self, time_filter="day", limit=10):
            return [_FakeSubmission("AI agent post", "https://example.com/1", "abc1")]

    class _FakeReddit:
        def __init__(self, *args, **kwargs):
            self._subs = {n: _FakeSubreddit() for n in ["MachineLearning", "LocalLLaMA", "OpenAI", "singularity", "AgentAI"]}

        def subreddit(self, name):
            return self._subs[name]

    # Inject a fake praw module via sys.modules so the in-function import works.
    import sys
    import types
    fake_praw = types.ModuleType("praw")
    fake_praw.Reddit = _FakeReddit  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "praw", fake_praw)

    items = await reddit_module.collect_reddit()
    assert len(items) >= 1
    assert items[0].sourceKey == SourceKey.REDDIT


# ---------- Web RSS collector ----------

@pytest.mark.asyncio
async def test_collect_web_parses_feed(monkeypatch, respx_mock):
    """Valid RSS feed returns RawItems via feedparser."""
    _patch_settings(monkeypatch)

    from app.pipeline.collectors import web as web_module

    rss = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Test</title>
    <item>
      <title>Agent framework released</title>
      <link>https://blog.example.com/post-1</link>
      <description>An autonomous agent library for coding workflows.</description>
      <pubDate>Mon, 12 Aug 2026 08:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""
    respx_mock.get(web_module.DEFAULT_FEEDS[0][1]).respond(200, text=rss)
    for _name, url in web_module.DEFAULT_FEEDS[1:]:
        respx_mock.get(url).respond(404)

    items = await web_module.collect_web()
    assert len(items) >= 1


@pytest.mark.asyncio
async def test_collect_web_all_failures_returns_empty(monkeypatch, respx_mock):
    """All feeds failing → return empty list."""
    _patch_settings(monkeypatch)

    from app.pipeline.collectors import web as web_module

    for _name, url in web_module.DEFAULT_FEEDS:
        respx_mock.get(url).respond(500)

    items = await web_module.collect_web()
    assert items == []


# ---------- X RSSHub collector ----------

@pytest.mark.asyncio
async def test_collect_x_rsshub_no_base_url_returns_empty(monkeypatch):
    """Without RSSHub base URL, return empty list (silent skip)."""
    _patch_settings(monkeypatch, AIDAILY_X_RSSHUB_BASE_URL="", AIDAILY_X_ACCOUNTS="karpathy,ylecun")

    from app.pipeline.collectors.x_rsshub import collect_x_rsshub

    items = await collect_x_rsshub()
    assert items == []


@pytest.mark.asyncio
async def test_collect_x_rsshub_parses_feed(monkeypatch, respx_mock):
    """With base URL + accounts, fetch + parse RSS."""
    _patch_settings(
        monkeypatch,
        AIDAILY_X_RSSHUB_BASE_URL="https://rsshub.example.com",
        AIDAILY_X_ACCOUNTS="karpathy",
    )

    from app.pipeline.collectors.x_rsshub import collect_x_rsshub

    rss = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>@karpathy</title>
    <item>
      <title>Tweet about agent frameworks</title>
      <link>https://x.com/karpathy/status/123</link>
      <description>autonomous agent library release</description>
      <pubDate>Mon, 12 Aug 2026 09:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""
    respx_mock.get("https://rsshub.example.com/twitter/user/karpathy").respond(200, text=rss)

    items = await collect_x_rsshub()
    assert len(items) == 1
    assert items[0].sourceKey == SourceKey.X
    assert "karpathy" in items[0].sourceName


@pytest.mark.asyncio
async def test_collect_x_rsshub_per_account_failure_continues(monkeypatch, respx_mock):
    """One account's feed fails, other accounts still return."""
    _patch_settings(
        monkeypatch,
        AIDAILY_X_RSSHUB_BASE_URL="https://rsshub.example.com",
        AIDAILY_X_ACCOUNTS="acc_a,acc_b",
    )

    from app.pipeline.collectors.x_rsshub import collect_x_rsshub

    rss = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>@acc_b</title>
    <item>
      <title>Working feed</title>
      <link>https://x.com/acc_b/status/1</link>
      <description>some content</description>
      <pubDate>Mon, 12 Aug 2026 09:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""
    respx_mock.get("https://rsshub.example.com/twitter/user/acc_a").respond(500)
    respx_mock.get("https://rsshub.example.com/twitter/user/acc_b").respond(200, text=rss)

    items = await collect_x_rsshub()
    assert len(items) == 1
    assert "acc_b" in items[0].sourceName


@pytest.mark.asyncio
async def test_collect_x_rsshub_uses_default_accounts_when_empty(monkeypatch, respx_mock):
    """No AIDAILY_X_ACCOUNTS → use defaults (T032 list)."""
    _patch_settings(
        monkeypatch,
        AIDAILY_X_RSSHUB_BASE_URL="https://rsshub.example.com",
        AIDAILY_X_ACCOUNTS="",
    )

    from app.pipeline.collectors.x_rsshub import collect_x_rsshub
    from app.pipeline.defaults.x_accounts import DEFAULT_X_ACCOUNTS

    # First default account returns a feed (empty body is fine)
    respx_mock.get(f"https://rsshub.example.com/twitter/user/{DEFAULT_X_ACCOUNTS[0]}").respond(
        200,
        text="""<?xml version="1.0"?>
<rss version="2.0">
  <channel><title>x</title></channel>
</rss>""",
    )
    # Others return 404
    for acc in DEFAULT_X_ACCOUNTS[1:]:
        respx_mock.get(f"https://rsshub.example.com/twitter/user/{acc}").respond(404)

    items = await collect_x_rsshub()
    assert isinstance(items, list)


__all__ = []