"""Unit tests for app/pipeline/collector.py orchestrator + dedup/classify helpers.

Covers:
- dedup_by_url: removes duplicates preserving order
- classify_type: keyword-based classifier for all 4 type keys
- collect_all: invokes 4 collectors, returns combined deduped + classified list
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.models.article import RawItem
from app.models.meta import SourceKey, TypeKey
from app.pipeline.collector import (
    CLASSIFY_KEYWORDS,
    classify_type,
    collect_all,
    dedup_by_url,
)


def _raw(source: SourceKey, url: str, title: str = "x", raw: str = "x") -> RawItem:
    return RawItem(
        sourceKey=source,
        sourceName=source.value,
        sourceUrl=url,
        title=title,
        rawText=raw,
        publishedAt="2026-08-12T08:00:00+00:00",
    )


# ---------- dedup_by_url ----------

def test_dedup_by_url_removes_duplicates():
    items = [
        _raw(SourceKey.GITHUB, "https://github.com/a"),
        _raw(SourceKey.WEB, "https://blog.example.com/post"),
        _raw(SourceKey.GITHUB, "https://github.com/a"),  # duplicate
        _raw(SourceKey.REDDIT, "https://reddit.com/r/x/1"),
    ]
    result = dedup_by_url(items)
    urls = [r.sourceUrl for r in result]
    assert len(result) == 3
    assert urls.count("https://github.com/a") == 1


def test_dedup_by_url_normalizes_trailing_slash():
    items = [
        _raw(SourceKey.WEB, "https://blog.example.com/post"),
        _raw(SourceKey.WEB, "https://blog.example.com/post/"),  # same with slash
    ]
    result = dedup_by_url(items)
    assert len(result) == 1


def test_dedup_by_url_preserves_first_seen_order():
    items = [
        _raw(SourceKey.GITHUB, "https://a.com/1"),
        _raw(SourceKey.WEB, "https://b.com/2"),
        _raw(SourceKey.GITHUB, "https://a.com/1"),
    ]
    result = dedup_by_url(items)
    assert result[0].sourceUrl == "https://a.com/1"
    assert result[1].sourceUrl == "https://b.com/2"


def test_dedup_by_url_empty():
    assert dedup_by_url([]) == []


# ---------- classify_type ----------

def test_classify_type_agent_keywords():
    """Agent-related text → AGENT."""
    assert classify_type(_raw(SourceKey.WEB, "https://x", raw="autonomous agent framework")) == TypeKey.AGENT


def test_classify_type_self_improve_keywords():
    """Learning-related text → SELF_IMPROVE."""
    # Use known keywords from CLASSIFY_KEYWORDS for SELF_IMPROVE
    assert classify_type(_raw(SourceKey.WEB, "https://x", raw="RLHF fine-tune approach for new model")) == TypeKey.SELF_IMPROVE
    assert classify_type(_raw(SourceKey.WEB, "https://x", raw="self-improvement paper")) == TypeKey.SELF_IMPROVE


def test_classify_type_open_source_keywords():
    """Repo/project text → OPEN_SOURCE."""
    assert classify_type(_raw(SourceKey.GITHUB, "https://github.com/x", raw="open-source library released on github")) == TypeKey.OPEN_SOURCE


def test_classify_type_tools_keywords():
    """Tool/CLI/library text → TOOLS."""
    assert classify_type(_raw(SourceKey.WEB, "https://x", raw="CLI tool for productivity")) == TypeKey.TOOLS


def test_classify_type_fallback_is_source_aware():
    """No keyword hit → GitHub lands open_source, others commentary (specs/005)."""
    assert classify_type(_raw(SourceKey.GITHUB, "https://github.com/x", raw="some random unrelated text")) == TypeKey.OPEN_SOURCE
    assert classify_type(_raw(SourceKey.X, "https://x.com/1", raw="some random unrelated text")) == TypeKey.COMMENTARY
    assert classify_type(_raw(SourceKey.REDDIT, "https://reddit.com/1", raw="some random unrelated text")) == TypeKey.COMMENTARY
    assert classify_type(_raw(SourceKey.WEB, "https://x", raw="some random unrelated text")) == TypeKey.COMMENTARY


def test_classify_type_tools_never_a_fallback():
    """tools only ever comes from an explicit keyword hit — a keyword-miss on
    any source must not produce TOOLS (specs/005)."""
    for src in SourceKey:
        assert classify_type(_raw(src, "https://x", raw="zzz qqq vvv")) != TypeKey.TOOLS


# ---------- CLASSIFY_KEYWORDS structure ----------

def test_classify_keywords_has_all_four_types():
    assert {TypeKey.AGENT, TypeKey.SELF_IMPROVE, TypeKey.OPEN_SOURCE, TypeKey.TOOLS} <= set(
        CLASSIFY_KEYWORDS.keys()
    )


# ---------- collect_all ----------

@pytest.mark.asyncio
async def test_collect_all_combines_sources(monkeypatch):
    """collect_all merges results from all 4 collectors + dedup + classify."""

    async def fake_github():
        return [_raw(SourceKey.GITHUB, "https://github.com/a", raw="agent framework")]

    async def fake_reddit():
        return [_raw(SourceKey.REDDIT, "https://reddit.com/r/x/1", raw="tool CLI")]

    async def fake_web():
        return [_raw(SourceKey.WEB, "https://blog.example.com/post", raw="open-source library")]

    async def fake_x():
        return [_raw(SourceKey.X, "https://x.com/user/status/1", raw="self-play improvement")]

    monkeypatch.setattr("app.pipeline.collector.collect_github", fake_github)
    monkeypatch.setattr("app.pipeline.collector.collect_reddit", fake_reddit)
    monkeypatch.setattr("app.pipeline.collector.collect_web", fake_web)
    monkeypatch.setattr("app.pipeline.collector.collect_x_rsshub", fake_x)

    items = await collect_all()
    assert len(items) == 4
    # Verify each was classified (keyword hit or source-aware fallback)
    for it in items:
        assert it.suggestedType is not None
        assert it.suggestedType in set(TypeKey)


@pytest.mark.asyncio
async def test_collect_all_partial_failure_logs_and_continues(monkeypatch):
    """If one collector raises, others' results still returned."""

    async def failing():
        raise RuntimeError("collector broken")

    async def empty():
        return []

    monkeypatch.setattr("app.pipeline.collector.collect_github", failing)
    monkeypatch.setattr("app.pipeline.collector.collect_reddit", empty)
    monkeypatch.setattr("app.pipeline.collector.collect_web", empty)
    monkeypatch.setattr("app.pipeline.collector.collect_x_rsshub", empty)

    items = await collect_all()
    assert items == []  # all others empty


@pytest.mark.asyncio
async def test_collect_all_dedupes_across_sources(monkeypatch):
    """Same URL from two sources → deduped to one."""

    async def a():
        return [_raw(SourceKey.GITHUB, "https://shared.example.com/post", raw="agent framework")]

    async def b():
        return [_raw(SourceKey.WEB, "https://shared.example.com/post", raw="different text")]

    async def c():
        return []

    async def d():
        return []

    monkeypatch.setattr("app.pipeline.collector.collect_github", a)
    monkeypatch.setattr("app.pipeline.collector.collect_reddit", b)
    monkeypatch.setattr("app.pipeline.collector.collect_web", c)
    monkeypatch.setattr("app.pipeline.collector.collect_x_rsshub", d)

    items = await collect_all()
    assert len(items) == 1


__all__ = []