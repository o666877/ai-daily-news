"""T022 / T013: Contract test for GET /articles/{id}.

Cases:
- 200 returns full Article (16 fields + US1 score object).
- 404 2001 not found.
- US1 T013: score object with compositeScore/dimensionScores/authorityTier/scoreSource.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from app.models.article import ArticleORM
from app.models.article_score import ArticleScoreORM


@pytest.mark.asyncio
async def test_articles_detail_200_full_fields(
    client: AsyncClient, ready_issue_with_articles
):
    """200 returns all fields per data-model.md §2 + US1 scoring fields.

    Pre-US1: 16 fields. US1: +compositeScore (int|null) at top level + score
    object (compositeScore/dimensionScores/authorityTier/scoreSource/topicId/
    opinionFingerprint | null).
    """
    issue, articles = ready_issue_with_articles
    article_id = articles[0].id
    res = await client.get(f"/api/v1/articles/{article_id}")
    assert res.status_code == 200, res.text
    body = res.json()
    expected_keys = {
        "id",
        "issueId",
        "type",
        "src",
        "title",
        "excerpt",
        "lede",
        "summary",
        "body",
        "quote",
        "points",
        "time",
        "sourceUrl",
        "sourceName",
        "readingMinutes",
        "publishedAt",
        # US1 fields
        "compositeScore",
        "score",
        "mustRead",
    }
    assert set(body.keys()) == expected_keys
    assert body["id"] == article_id
    assert body["type"] in {"agent", "self_improve", "open_source", "tools"}
    assert body["src"] in {"x", "github", "reddit", "web"}
    assert isinstance(body["body"], str) and len(body["body"]) >= 1
    assert isinstance(body["points"], list) and len(body["points"]) >= 1


@pytest.mark.asyncio
async def test_articles_detail_404_not_found(client: AsyncClient):
    """404 2001 when article id doesn't exist."""
    res = await client.get("/api/v1/articles/nonexistent")
    assert res.status_code == 404, res.text
    body = res.json()
    assert body["code"] == 2001
    assert body["requestId"]


# ---------- US1 T013: score object ----------

async def _seed_article_with_score(
    db_session, article_id: str, source_name: str, tier: str, composite: int
):
    """Helper: build article + ArticleScoreORM row directly."""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_gen = datetime.now(timezone.utc)
    from app.models.daily_issue import DailyIssueORM

    issue = DailyIssueORM(
        id=today,
        date=today_iso,
        edition=1,
        status="ready",
        generated_at=today_gen,
        filters_applied={"sources": [], "types": []},
    )
    db_session.add(issue)
    await db_session.commit()

    art = ArticleORM(
        id=article_id,
        issue_id=today,
        type="agent",
        src="web",
        title="Scored Article",
        excerpt="excerpt",
        lede="lede",
        summary="summary",
        body="body",
        quote=None,
        points=["point"],
        time="09:00",
        source_url="https://example.com",
        source_name=source_name,
        reading_minutes=3,
        published_at="2026-08-12T09:00:00+00:00",
    )
    db_session.add(art)
    score = ArticleScoreORM(
        article_id=article_id,
        composite_score=composite,
        dim_authority=90,
        dim_depth=80,
        dim_timeliness=70,
        dim_expression=60,
        authority_tier=tier,
        topic_id="some-topic",
        opinion_fingerprint="analysis",
        score_source="llm",
        computed_at=datetime.utcnow(),
    )
    db_session.add(score)
    await db_session.commit()
    return art


@pytest.mark.asyncio
async def test_articles_detail_includes_score_object(
    client: AsyncClient, db_session
):
    """US1 T013: detail response includes score sub-object with required fields."""
    await _seed_article_with_score(
        db_session,
        article_id="20260812-SCORE-1",
        source_name="openai.com/blog/x",
        tier="official_blog",
        composite=88,
    )
    res = await client.get("/api/v1/articles/20260812-SCORE-1")
    assert res.status_code == 200, res.text
    body = res.json()
    assert "score" in body
    score = body["score"]
    assert score is not None
    assert score["compositeScore"] == 88
    assert 0 <= score["compositeScore"] <= 100
    # Required sub-fields
    assert set(score.keys()) >= {
        "compositeScore",
        "dimensionScores",
        "authorityTier",
        "scoreSource",
    }
    assert score["authorityTier"] == "official_blog"
    assert score["scoreSource"] == "llm"
    # dimensionScores must have 5 keys (v2: + engagement)
    dims = score["dimensionScores"]
    assert set(dims.keys()) == {
        "authority",
        "depth",
        "timeliness",
        "expression",
        "engagement",
    }
    assert all(isinstance(v, int) and 0 <= v <= 100 for v in dims.values())


@pytest.mark.asyncio
async def test_articles_detail_score_null_when_no_score_row(
    client: AsyncClient, ready_issue_with_articles
):
    """US1 T013: when article has no score row (legacy data), score is null."""
    issue, articles = ready_issue_with_articles
    article_id = articles[0].id
    res = await client.get(f"/api/v1/articles/{article_id}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("score") is None


@pytest.mark.asyncio
async def test_articles_detail_score_includes_optional_dedup_fields(
    client: AsyncClient, db_session
):
    """US1 T013: topicId and opinionFingerprint appear when populated."""
    await _seed_article_with_score(
        db_session,
        article_id="20260812-SCORE-2",
        source_name="stratechery.com",
        tier="authoritative_media",
        composite=75,
    )
    res = await client.get("/api/v1/articles/20260812-SCORE-2")
    body = res.json()
    score = body["score"]
    assert score["topicId"] == "some-topic"
    assert score["opinionFingerprint"] == "analysis"
