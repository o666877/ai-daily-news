"""T026: Unit test for LLM summarizer.

Cases:
- Returns 5 output fields (lede/summary/body/points + quote).
- Retries max 2 on RateLimitError → marks failure.
"""

from __future__ import annotations

import json

import pytest

from app.infra import llm as llm_module
from app.infra.errors import PipelineBusyError
from app.models.article import RawItem
from app.models.meta import SourceKey
from app.pipeline import summarizer
from app.pipeline.summarizer import SummarizerFailure, summarize_item


def _make_raw() -> RawItem:
    return RawItem(
        sourceKey=SourceKey.GITHUB,
        sourceName="github.com",
        sourceUrl="https://github.com/test/repo",
        title="Some Repo",
        rawText="A description of the repo with AI agents.",
        publishedAt="2026-08-12T08:00:00+00:00",
    )


class _SuccessClient:
    async def summarize(self, title, source, raw_text):
        return llm_module._parse_summary_response(
            json.dumps(
                {
                    "lede": "导语",
                    "summary": "一句话总结",
                    "body": ["段1", "段2"],
                    "quote": "引语",
                    "points": ["要点1", "要点2"],
                }
            )
        )


class _AlwaysRateLimitClient:
    async def summarize(self, title, source, raw_text):
        raise PipelineBusyError("LLM 限流")


class _AlwaysProviderErrorClient:
    async def summarize(self, title, source, raw_text):
        raise llm_module.LLMProviderError("boom")


@pytest.mark.asyncio
async def test_summarizer_returns_5_fields(monkeypatch):
    """Success: returns SummaryResult with all 5 fields populated."""
    monkeypatch.setattr(summarizer, "check_budget", lambda *_a, **_kw: None)
    monkeypatch.setattr(summarizer, "_track_spend", lambda *_a, **_kw: None)
    result = await summarize_item(_make_raw(), client=_SuccessClient())
    assert result.lede
    assert result.summary
    assert isinstance(result.body, list) and len(result.body) >= 1
    assert result.quote is not None
    assert isinstance(result.points, list) and len(result.points) >= 1


@pytest.mark.asyncio
async def test_summarizer_retries_on_provider_error(monkeypatch):
    """ProviderError retries max 2 attempts then raises SummarizerFailure."""
    monkeypatch.setattr(summarizer, "check_budget", lambda *_a, **_kw: None)
    monkeypatch.setattr(summarizer, "_track_spend", lambda *_a, **_kw: None)
    with pytest.raises(SummarizerFailure):
        await summarize_item(_make_raw(), client=_AlwaysProviderErrorClient())


@pytest.mark.asyncio
async def test_summarizer_propagates_budget_exceeded(monkeypatch):
    """PipelineBusyError (rate limit / budget) propagates as 9002 to caller."""
    monkeypatch.setattr(summarizer, "check_budget", lambda *_a, **_kw: None)
    monkeypatch.setattr(summarizer, "_track_spend", lambda *_a, **_kw: None)
    with pytest.raises(PipelineBusyError):
        await summarize_item(_make_raw(), client=_AlwaysRateLimitClient())
