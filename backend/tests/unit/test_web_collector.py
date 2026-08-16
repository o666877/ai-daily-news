"""Unit tests for the web RSS collector.

Covers:
- Default feed list liveness contract (>= 8 active sources).
- 72h freshness soft threshold (_filter_fresh).
- Per-entry fresh metadata in RawItem.extra.
- collect_web survives partial feed failures.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.models.article import RawItem
from app.models.meta import SourceKey
from app.pipeline.collectors import web as web_module


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class _FakeEntry:
    """Mimic a feedparser entry for _filter_fresh / _entry_age_hours."""

    def __init__(self, age_hours: float | None, link: str = "https://example.com/x") -> None:
        self.link = link
        if age_hours is None:
            self.published_parsed = None
            self.updated_parsed = None
            self.published = None
            self.updated = None
            return
        dt = datetime.now(tz=timezone.utc) - timedelta(hours=age_hours)
        st = dt.utctimetuple()
        self.published_parsed = st
        self.updated_parsed = st
        self.published = dt.isoformat()
        self.updated = dt.isoformat()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


# ---------------------------------------------------------------------------
# Feed list liveness contract
# ---------------------------------------------------------------------------


def test_default_sources_has_eight_active_feeds():
    """At least 8 curated feeds — prevents silent shrinkage after edits."""
    assert len(web_module.DEFAULT_SOURCES) >= 8
    # All entries are (str, str) tuples.
    for entry in web_module.DEFAULT_SOURCES:
        assert isinstance(entry, tuple) and len(entry) == 2
        name, url = entry
        assert name and url.startswith("http")


def test_default_feeds_alias_matches_sources():
    assert web_module.DEFAULT_FEEDS is web_module.DEFAULT_SOURCES


# ---------------------------------------------------------------------------
# Freshness threshold
# ---------------------------------------------------------------------------


def test_filter_fresh_keeps_recent_and_drops_stale():
    """Entries within the 72h window are kept; older entries are dropped."""
    entries = [
        _FakeEntry(age_hours=1, link="https://example.com/1"),
        _FakeEntry(age_hours=24, link="https://example.com/2"),
        _FakeEntry(age_hours=71, link="https://example.com/3"),  # boundary: kept
        _FakeEntry(age_hours=73, link="https://example.com/4"),  # dropped
        _FakeEntry(age_hours=240, link="https://example.com/5"),  # dropped
    ]
    kept, dropped = web_module._filter_fresh(entries, hours=72)
    assert len(kept) == 3
    assert dropped == 2
    kept_links = [e.link for e in kept]
    assert "https://example.com/1" in kept_links
    assert "https://example.com/4" not in kept_links


def test_filter_fresh_keeps_entries_without_timestamp():
    """Missing timestamps do NOT silently drop — we don't punish missing dates."""
    entries = [
        _FakeEntry(age_hours=None, link="https://example.com/n1"),
        _FakeEntry(age_hours=10, link="https://example.com/n2"),
    ]
    kept, dropped = web_module._filter_fresh(entries, hours=72)
    assert len(kept) == 2
    assert dropped == 0


def test_entry_age_hours_returns_none_when_no_timestamp():
    assert web_module._entry_age_hours(_FakeEntry(age_hours=None)) is None
    assert web_module._entry_age_hours(_FakeEntry(age_hours=5)) == pytest.approx(5, abs=1)


def test_oldest_age_hours_picks_max():
    entries = [
        _FakeEntry(age_hours=1),
        _FakeEntry(age_hours=100),
        _FakeEntry(age_hours=50),
    ]
    assert web_module._oldest_age_hours(entries) == pytest.approx(100, abs=1)


def test_oldest_age_hours_none_when_all_missing():
    entries = [_FakeEntry(age_hours=None), _FakeEntry(age_hours=None)]
    assert web_module._oldest_age_hours(entries) is None


# ---------------------------------------------------------------------------
# Build-item integration: fresh flag in extra
# ---------------------------------------------------------------------------


def _make_entry(age_hours: float | None, link: str):
    """Build a feedparser-like entry for _build_item."""

    class E:
        pass

    e = E()
    e.title = "t"
    e.link = link
    e.description = "desc"
    e.content = [{"value": "desc"}]
    if age_hours is not None:
        dt = datetime.now(tz=timezone.utc) - timedelta(hours=age_hours)
        st = dt.utctimetuple()
        e.published_parsed = st
        e.updated_parsed = st
        e.published = dt.isoformat()
        e.updated = dt.isoformat()
    else:
        e.published_parsed = None
        e.updated_parsed = None
        e.published = None
        e.updated = None
    return e


def test_build_item_marks_fresh_true_within_window():
    item = web_module._build_item("Test", "https://feed", _make_entry(2, "https://x/1"), "https://x/1")
    assert item is not None
    assert item.extra["fresh"] is True
    assert item.extra["age_h"] == pytest.approx(2, abs=1)


def test_build_item_marks_fresh_false_outside_window():
    item = web_module._build_item("Test", "https://feed", _make_entry(120, "https://x/2"), "https://x/2")
    assert item is not None
    assert item.extra["fresh"] is False


def test_build_item_fresh_none_when_no_timestamp():
    item = web_module._build_item("Test", "https://feed", _make_entry(None, "https://x/3"), "https://x/3")
    assert item is not None
    # When we can't tell, default to fresh=True so we don't accidentally drop.
    assert item.extra["fresh"] is True
    assert item.extra["age_h"] is None


# ---------------------------------------------------------------------------
# collect_web: per-source failure tolerance (respx)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_collect_web_survives_partial_failure(monkeypatch, respx_mock):
    """Some feeds 200, some 500 → items from 200'd feeds survive; no raise."""
    # Make first feed return one fresh entry; rest fail.
    from tests.unit.test_individual_collectors import _patch_settings

    _patch_settings(monkeypatch)

    fresh = _make_entry(age_hours=1, link="https://example.com/fresh")
    rss = (
        "<?xml version='1.0'?>"
        "<rss version='2.0'><channel><title>t</title>"
        "<item><title>x</title>"
        "<link>https://example.com/fresh</link>"
        "<description>d</description>"
        "<pubDate>Mon, 12 Aug 2026 08:00:00 GMT</pubDate>"
        "</item></channel></rss>"
    )
    name0, url0 = web_module.DEFAULT_FEEDS[0]
    respx_mock.get(url0).respond(200, text=rss)
    for _n, u in web_module.DEFAULT_FEEDS[1:]:
        respx_mock.get(u).respond(500)

    items = await web_module.collect_web()
    assert any(it.sourceUrl == "https://example.com/fresh" for it in items)
    # The surviving item came from the first source.
    assert items[0].sourceName == name0


@pytest.mark.asyncio
async def test_collect_web_all_failures_returns_empty(monkeypatch, respx_mock):
    from tests.unit.test_individual_collectors import _patch_settings

    _patch_settings(monkeypatch)

    for _n, u in web_module.DEFAULT_FEEDS:
        respx_mock.get(u).respond(500)

    items = await web_module.collect_web()
    assert items == []


@pytest.mark.asyncio
async def test_collect_web_stale_entries_are_filtered(monkeypatch, respx_mock):
    """All entries from a feed older than 72h → log web_feed_stale + 0 items from that feed."""
    from tests.unit.test_individual_collectors import _patch_settings

    _patch_settings(monkeypatch)

    # Build an RSS with entries backdated to 100h ago — all stale.
    past = datetime.now(tz=timezone.utc) - timedelta(hours=100)
    rfc = past.strftime("%a, %d %b %Y %H:%M:%S GMT")
    rss = (
        "<?xml version='1.0'?>"
        "<rss version='2.0'><channel><title>t</title>"
        "<item><title>stale1</title>"
        "<link>https://example.com/stale1</link>"
        "<description>d</description>"
        f"<pubDate>{rfc}</pubDate></item>"
        "<item><title>stale2</title>"
        "<link>https://example.com/stale2</link>"
        "<description>d</description>"
        f"<pubDate>{rfc}</pubDate></item>"
        "</channel></rss>"
    )
    name0, url0 = web_module.DEFAULT_FEEDS[0]
    respx_mock.get(url0).respond(200, text=rss)
    for _n, u in web_module.DEFAULT_FEEDS[1:]:
        respx_mock.get(u).respond(404)

    items = await web_module.collect_web()
    # First feed should have produced 0 items because all entries were >72h.
    assert all(it.sourceName != name0 for it in items)