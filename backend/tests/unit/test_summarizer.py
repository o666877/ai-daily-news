"""T026: Unit test for LLM summarizer.

Cases:
- Returns 5 output fields (lede/summary/body/points + quote).
- Retries max 2 on RateLimitError → marks failure.
- US1 T012: extends to scoring fields (authority override via classify_authority,
  compose_score, rule_fallback on LLM failure).
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


def _make_raw(source_name: str = "github.com", extra: dict | None = None) -> RawItem:
    return RawItem(
        sourceKey=SourceKey.GITHUB,
        sourceName=source_name,
        sourceUrl="https://github.com/test/repo",
        title="Some Repo",
        rawText="A description of the repo with AI agents.",
        publishedAt="2026-08-12T08:00:00+00:00",
        extra=extra,
    )


class _SuccessClient:
    """Returns a fully-populated SummaryResult with all 4 dimensions + dedup fields."""

    async def summarize(self, title, source, raw_text):
        return llm_module._parse_summary_response(
            json.dumps(
                {
                    "title": "中文标题",
                    "lede": "导语",
                    "summary": "一句话总结",
                    "body": "段1\n\n段2",
                    "quote": "引语",
                    "points": ["要点1", "要点2"],
                    "dimensionScores": {
                        "authority": 50,  # LLM guess — will be overridden by rule
                        "depth": 85,
                        "timeliness": 70,
                        "expression": 65,
                    },
                    "topicId": "github-repo-release",
                    "opinionFingerprint": "first-person",
                },
                ensure_ascii=False,
            )
        )


class _AlwaysBudgetExceededClient:
    """Simulates daily budget exhaustion — PipelineBusyError raised by
    check_budget(), non-retryable, must propagate (do NOT fallback)."""

    async def summarize(self, title, source, raw_text):
        raise PipelineBusyError("daily budget exhausted")


class _AlwaysProviderErrorClient:
    async def summarize(self, title, source, raw_text):
        raise llm_module.LLMProviderError("boom")


class _AlwaysRateLimitClient:
    """Simulates provider 429 — surfaces as LLMRateLimitError (retryable).
    After tenacity exhausts → rule_fallback (NOT propagate)."""

    async def summarize(self, title, source, raw_text):
        raise llm_module.LLMRateLimitError("LLM 限流")


@pytest.mark.asyncio
async def test_summarizer_returns_6_fields(monkeypatch):
    """Success: returns SummaryResult with all 6 fields populated (incl. title)."""
    monkeypatch.setattr(summarizer, "check_budget", lambda *_a, **_kw: None)
    monkeypatch.setattr(summarizer, "_track_spend", lambda *_a, **_kw: None)
    result = await summarize_item(_make_raw(), client=_SuccessClient())
    assert result.title
    assert result.lede
    assert result.summary
    assert isinstance(result.body, str) and len(result.body) >= 1
    assert result.quote is not None
    assert isinstance(result.points, list) and len(result.points) >= 1


@pytest.mark.asyncio
async def test_summarizer_retries_on_provider_error(monkeypatch):
    """ProviderError after retries → falls back to rule_fallback (US1 T012).

    Pre-US1: this raised SummarizerFailure. Post-US1: the summarizer's
    safety net returns a rule-derived SummaryResult instead, so transient
    LLM failures don't drop articles from the daily issue.
    """
    monkeypatch.setattr(summarizer, "check_budget", lambda *_a, **_kw: None)
    monkeypatch.setattr(summarizer, "_track_spend", lambda *_a, **_kw: None)
    result = await summarize_item(_make_raw(), client=_AlwaysProviderErrorClient())
    assert result.score_source == "rule_fallback"
    assert result.dimension_scores is not None
    # github.com → community → 50
    assert result.dimension_scores["authority"] == 50
    assert result.authority_tier == "community"


@pytest.mark.asyncio
async def test_summarizer_propagates_budget_exceeded(monkeypatch):
    """Budget exhaustion → PipelineBusyError → propagate as 9002 to caller
    (check_budget raises this from inside _summarize_with_retry; tenacity
    does not retry it; summarize_item re-raises). No rule_fallback."""
    monkeypatch.setattr(summarizer, "check_budget", lambda *_a, **_kw: None)
    monkeypatch.setattr(summarizer, "_track_spend", lambda *_a, **_kw: None)
    with pytest.raises(PipelineBusyError):
        await summarize_item(_make_raw(), client=_AlwaysBudgetExceededClient())


@pytest.mark.asyncio
async def test_summarizer_rate_limit_falls_back(monkeypatch):
    """Provider 429 → LLMRateLimitError → tenacity retries (2x) → still
    failing → rule_fallback (does NOT propagate, does NOT mark issue failed).
    This is the contract change from the previous behavior where 429 was
    mis-mapped to PipelineBusyError and brought down the whole issue."""
    monkeypatch.setattr(summarizer, "check_budget", lambda *_a, **_kw: None)
    monkeypatch.setattr(summarizer, "_track_spend", lambda *_a, **_kw: None)
    result = await summarize_item(_make_raw(), client=_AlwaysRateLimitClient())
    assert result.score_source == "rule_fallback"
    assert result.dimension_scores is not None


# ---------- US1 T012: scoring + authority override ----------

@pytest.mark.asyncio
async def test_summarizer_success_overrides_authority_via_rule(monkeypatch):
    """LLM-success path: dim_authority overridden by classify_authority(sourceName).

    The LLM may output authority=50 for github.com source, but the system rule
    must override it. github.com → community tier → authority=50.
    """
    monkeypatch.setattr(summarizer, "check_budget", lambda *_a, **_kw: None)
    monkeypatch.setattr(summarizer, "_track_spend", lambda *_a, **_kw: None)
    result = await summarize_item(_make_raw("github.com"), client=_SuccessClient())
    assert result.dimension_scores is not None
    # github.com → community → 50
    assert result.dimension_scores["authority"] == 50
    assert result.authority_tier == "community"


@pytest.mark.asyncio
async def test_summarizer_success_official_blog_overrides_authority(monkeypatch):
    """openai.com source → authority=90 even if LLM output 50."""
    monkeypatch.setattr(summarizer, "check_budget", lambda *_a, **_kw: None)
    monkeypatch.setattr(summarizer, "_track_spend", lambda *_a, **_kw: None)
    raw = _make_raw("openai.com/blog/something")
    raw = RawItem(**{**raw.model_dump(), "sourceKey": SourceKey.WEB})
    result = await summarize_item(raw, client=_SuccessClient())
    assert result.dimension_scores is not None
    assert result.dimension_scores["authority"] == 90
    assert result.authority_tier == "official_blog"


@pytest.mark.asyncio
async def test_summarizer_success_keeps_llm_depth_timeliness_expression(monkeypatch):
    """Non-authority dimensions preserved from LLM output."""
    monkeypatch.setattr(summarizer, "check_budget", lambda *_a, **_kw: None)
    monkeypatch.setattr(summarizer, "_track_spend", lambda *_a, **_kw: None)
    result = await summarize_item(_make_raw("github.com"), client=_SuccessClient())
    assert result.dimension_scores is not None
    assert result.dimension_scores["depth"] == 85
    assert result.dimension_scores["timeliness"] == 70
    assert result.dimension_scores["expression"] == 65


@pytest.mark.asyncio
async def test_summarizer_success_computes_composite_score(monkeypatch):
    """Composite score = weighted sum; reflect authority override."""
    monkeypatch.setattr(summarizer, "check_budget", lambda *_a, **_kw: None)
    monkeypatch.setattr(summarizer, "_track_spend", lambda *_a, **_kw: None)
    result = await summarize_item(_make_raw("github.com"), client=_SuccessClient())
    # community authority=50, no extra → engagement=50:
    # 50*0.25 + 85*0.25 + 50*0.25 + 70*0.15 + 65*0.10 = 12.5+21.25+12.5+10.5+6.5 = 63.25 → 63
    assert result.composite_score == 63
    assert 0 <= result.composite_score <= 100


@pytest.mark.asyncio
async def test_summarizer_engagement_from_stars_beats_neutral(monkeypatch):
    """GitHub stars flow through extra → engagement dim → composite."""
    monkeypatch.setattr(summarizer, "check_budget", lambda *_a, **_kw: None)
    monkeypatch.setattr(summarizer, "_track_spend", lambda *_a, **_kw: None)
    no_stars = await summarize_item(_make_raw("github.com"), client=_SuccessClient())
    starred = await summarize_item(
        _make_raw("github.com", extra={"stars": 10_000}), client=_SuccessClient()
    )
    assert no_stars.dimension_scores["engagement"] == 50
    assert starred.dimension_scores["engagement"] == 93
    assert starred.composite_score > no_stars.composite_score


@pytest.mark.asyncio
async def test_summarizer_success_dedup_signals_propagated(monkeypatch):
    """topic_id + opinion_fingerprint propagated from LLM to SummaryResult."""
    monkeypatch.setattr(summarizer, "check_budget", lambda *_a, **_kw: None)
    monkeypatch.setattr(summarizer, "_track_spend", lambda *_a, **_kw: None)
    result = await summarize_item(_make_raw("github.com"), client=_SuccessClient())
    assert result.topic_id == "github-repo-release"
    assert result.opinion_fingerprint == "first-person"


@pytest.mark.asyncio
async def test_summarizer_success_score_source_is_llm(monkeypatch):
    """LLM-success path → score_source='llm'."""
    monkeypatch.setattr(summarizer, "check_budget", lambda *_a, **_kw: None)
    monkeypatch.setattr(summarizer, "_track_spend", lambda *_a, **_kw: None)
    result = await summarize_item(_make_raw("github.com"), client=_SuccessClient())
    assert result.score_source == "llm"


@pytest.mark.asyncio
async def test_summarizer_llm_failure_falls_back_to_rules(monkeypatch):
    """On LLM failure, summarize_item falls back to score_with_rules + score_source='rule_fallback'.

    Returns a SummaryResult populated with rule-derived scoring fields plus a
    minimal title/excerpt from rawText. Other narrative fields (lede/body/etc.)
    are empty since LLM did not produce them.
    """
    monkeypatch.setattr(summarizer, "check_budget", lambda *_a, **_kw: None)
    monkeypatch.setattr(summarizer, "_track_spend", lambda *_a, **_kw: None)
    # ProviderError raises SummarizerFailure today; but with rule_fallback we
    # expect summarize_item to CATCH the failure and return a rule-derived
    # SummaryResult instead.
    result = await summarize_item(_make_raw("openai.com/blog"), client=_AlwaysProviderErrorClient())
    assert result.score_source == "rule_fallback"
    assert result.dimension_scores is not None
    # openai.com → official_blog → 90
    assert result.dimension_scores["authority"] == 90
    assert result.authority_tier == "official_blog"
    # rule_fallback depth is heuristic on raw_text length
    assert 0 <= result.dimension_scores["depth"] <= 100
    assert result.dimension_scores["expression"] == 50  # neutral default
    assert 0 <= result.composite_score <= 100


__all__ = []
