"""T021 / T014: Contract test for GET /daily/today.

Cases:
- 200 ready issue with issue + summary + articles.
- 404 2002 not generated.
- 409 2003 generating.
- Empty articles (status=ready but 0 items).
- US1 T014: each article has compositeScore; ordering compositeScore DESC, time DESC.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.models.article import ArticleORM
from app.models.article_score import ArticleScoreORM
from app.models.daily_issue import DailyIssueORM
from datetime import datetime, timezone


@pytest.mark.asyncio
async def test_daily_today_200_ready(client: AsyncClient, ready_issue_with_articles):
    """200 with issue.status=ready, articleCount≥1, articles length matches."""
    res = await client.get("/api/v1/daily/today")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["issue"]["status"] == "ready"
    assert body["issue"]["articleCount"] == 2
    assert len(body["articles"]) == 2
    # Per item: original 7 fields + US1 compositeScore
    first = body["articles"][0]
    expected_keys = {
        "id",
        "title",
        "excerpt",
        "type",
        "src",
        "time",
        "readingMinutes",
        "publishedAt",
        "compositeScore",
        "mustRead",
    }
    assert set(first.keys()) == expected_keys
    # summary has both byType and bySource with all 4 keys
    assert set(body["summary"]["byType"].keys()) == {
        "agent", "self_improve", "open_source", "tools", "commentary",
    }
    assert set(body["summary"]["bySource"].keys()) == {"x", "github", "reddit", "web"}


@pytest.mark.asyncio
async def test_daily_today_404_not_generated(client: AsyncClient, db_session):
    """404 2002 when no issue exists for today."""
    res = await client.get("/api/v1/daily/today")
    assert res.status_code == 404, res.text
    body = res.json()
    assert body["code"] == 2002
    assert "requestId" in body and body["requestId"]


@pytest.mark.asyncio
async def test_daily_today_409_generating(client: AsyncClient, db_session):
    """409 2003 when issue status=generating."""
    from datetime import datetime, timezone

    issue = DailyIssueORM(
        id=__import__("datetime").datetime.now(timezone.utc).strftime("%Y%m%d"),
        date=__import__("datetime").datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        edition=1,
        status="generating",
        generated_at=None,
        filters_applied={"sources": [], "types": []},
    )
    db_session.add(issue)
    await db_session.commit()

    res = await client.get("/api/v1/daily/today")
    assert res.status_code == 409, res.text
    body = res.json()
    assert body["code"] == 2003


@pytest.mark.asyncio
async def test_daily_today_empty_articles(client: AsyncClient, db_session):
    """200 ready with 0 articles returns empty list + zeroed summary."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    issue = DailyIssueORM(
        id=now.strftime("%Y%m%d"),
        date=now.strftime("%Y-%m-%d"),
        edition=1,
        status="ready",
        generated_at=now,
        filters_applied={"sources": ["x"], "types": ["agent"]},
    )
    db_session.add(issue)
    await db_session.commit()

    res = await client.get("/api/v1/daily/today")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["issue"]["articleCount"] == 0
    assert body["articles"] == []


# ---------- US1 T014: compositeScore per item + ordering ----------

async def _seed_scored_articles(db_session, scored: list[tuple[str, int, str]]):
    """Seed an issue + N articles with given (id_suffix, composite_score, time)."""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_gen = datetime.now(timezone.utc)
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

    for suffix, composite, time_label in scored:
        art_id = f"{today}-{suffix}"
        art = ArticleORM(
            id=art_id,
            issue_id=today,
            type="agent",
            src="web",
            title=f"Title {suffix}",
            excerpt="excerpt",
            lede="lede",
            summary="summary",
            body="body",
            quote=None,
            points=["point"],
            time=time_label,
            source_url=f"https://example.com/{suffix}",
            source_name="openai.com",
            reading_minutes=3,
            published_at="2026-08-12T09:00:00+00:00",
        )
        db_session.add(art)
        score = ArticleScoreORM(
            article_id=art_id,
            composite_score=composite,
            dim_authority=90,
            dim_depth=80,
            dim_timeliness=70,
            dim_expression=60,
            authority_tier="official_blog",
            topic_id=None,
            opinion_fingerprint=None,
            score_source="llm",
            computed_at=datetime.utcnow(),
        )
        db_session.add(score)
    await db_session.commit()


@pytest.mark.asyncio
async def test_daily_today_each_article_has_compositeScore(client: AsyncClient, db_session):
    """US1 T014: every article in /daily/today has compositeScore field."""
    await _seed_scored_articles(
        db_session,
        [
            ("D01", 80, "09:00"),
            ("D02", 75, "10:00"),
        ],
    )
    res = await client.get("/api/v1/daily/today")
    body = res.json()
    assert len(body["articles"]) == 2
    for a in body["articles"]:
        assert "compositeScore" in a
        assert isinstance(a["compositeScore"], int)
        assert 0 <= a["compositeScore"] <= 100


@pytest.mark.asyncio
async def test_daily_today_sorted_by_composite_score_desc_then_time_desc(
    client: AsyncClient, db_session
):
    """US1 T014: ordering compositeScore DESC, then time DESC for ties."""
    await _seed_scored_articles(
        db_session,
        [
            ("LOW", 50, "08:00"),
            ("HIGH", 90, "12:00"),
            ("MID", 70, "10:00"),
            ("MIDLATE", 70, "11:00"),
        ],
    )
    res = await client.get("/api/v1/daily/today")
    body = res.json()
    items = body["articles"]
    ids_in_order = [it["id"].split("-")[-1] for it in items]
    # Expected: HIGH (90), MIDLATE (70, 11:00), MID (70, 10:00), LOW (50)
    assert ids_in_order == ["HIGH", "MIDLATE", "MID", "LOW"]


@pytest.mark.asyncio
async def test_daily_today_compositeScore_null_for_legacy_rows(
    client: AsyncClient, ready_issue_with_articles
):
    """US1 T014: legacy articles without score rows return compositeScore=null."""
    res = await client.get("/api/v1/daily/today")
    body = res.json()
    assert len(body["articles"]) >= 1
    for a in body["articles"]:
        assert "compositeScore" in a
        assert a["compositeScore"] is None
