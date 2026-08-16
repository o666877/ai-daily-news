"""T052 / T014: Contract tests for GET /api/v1/articles list filtering.

US1 T014: each item includes compositeScore; ordering is compositeScore DESC, time DESC.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from app.models.article import ArticleORM
from app.models.article_score import ArticleScoreORM
from app.models.daily_issue import DailyIssueORM


@pytest.mark.asyncio
async def test_articles_list_filters_and_echoes(client: AsyncClient, ready_issue_with_articles):
    response = await client.get(
        "/api/v1/articles", params={"type": "agent", "src": "reddit"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["appliedFilters"] == {"type": "agent", "src": "reddit"}
    assert body["page"] == 1
    assert body["pageSize"] == 20
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["type"] == "agent"
    assert body["items"][0]["src"] == "reddit"


@pytest.mark.asyncio
async def test_articles_list_empty_items(client: AsyncClient, ready_issue_with_articles):
    response = await client.get("/api/v1/articles", params={"type": "agent", "src": "x"})
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0
    assert body["appliedFilters"] == {"type": "agent", "src": "x"}


@pytest.mark.asyncio
@pytest.mark.parametrize("params", [{"type": "invalid"}, {"src": "wechat"}])
async def test_articles_list_invalid_enum(client: AsyncClient, params):
    response = await client.get("/api/v1/articles", params=params)
    assert response.status_code == 400
    assert response.json()["code"] == 1002


@pytest.mark.asyncio
async def test_articles_list_page_out_of_range(client: AsyncClient):
    response = await client.get("/api/v1/articles", params={"page": 0})
    assert response.status_code == 400
    body = response.json()
    assert body["code"] in {1002, 1005}


@pytest.mark.asyncio
async def test_articles_list_rate_limit(client: AsyncClient, ready_issue_with_articles):
    from app.infra.ratelimit import read_limiter

    read_limiter.reset()
    # Drive the underlying slowapi storage above the limit by hammering it.
    for _ in range(125):
        await client.get("/api/v1/articles")
    response = await client.get("/api/v1/articles")
    assert response.status_code == 429
    assert response.json()["code"] == 1006
    read_limiter.reset()


# ---------- US1 T014: compositeScore per item + ordering ----------

async def _seed_scored_articles(db_session, scored: list[tuple[str, int, str]]):
    """Seed an issue + N articles with given (id_suffix, composite_score, time) tuples."""
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
async def test_articles_list_each_item_has_compositeScore(client: AsyncClient, db_session):
    """US1 T014: every item in /articles has compositeScore field."""
    await _seed_scored_articles(
        db_session,
        [
            ("S01", 80, "09:00"),
            ("S02", 75, "10:00"),
        ],
    )
    res = await client.get("/api/v1/articles")
    body = res.json()
    assert body["total"] == 2
    for item in body["items"]:
        assert "compositeScore" in item
        assert isinstance(item["compositeScore"], int)
        assert 0 <= item["compositeScore"] <= 100


@pytest.mark.asyncio
async def test_articles_list_sorted_by_composite_score_desc_then_time_desc(
    client: AsyncClient, db_session
):
    """US1 T014: ordering is compositeScore DESC, then time DESC for ties."""
    await _seed_scored_articles(
        db_session,
        [
            ("LOW", 50, "08:00"),
            ("HIGH", 90, "12:00"),
            ("MID", 70, "10:00"),
            # Tie at 70 — should order by time DESC
            ("MIDLATE", 70, "11:00"),
        ],
    )
    res = await client.get("/api/v1/articles")
    body = res.json()
    items = body["items"]
    ids_in_order = [it["id"].split("-")[-1] for it in items]
    # Expected: HIGH (90), MIDLATE (70, 11:00), MID (70, 10:00), LOW (50)
    assert ids_in_order == ["HIGH", "MIDLATE", "MID", "LOW"]


@pytest.mark.asyncio
async def test_articles_list_compositeScore_null_for_legacy_rows(
    client: AsyncClient, ready_issue_with_articles
):
    """US1 T014: legacy articles without score rows return compositeScore=null."""
    res = await client.get("/api/v1/articles")
    body = res.json()
    assert body["total"] >= 1
    for item in body["items"]:
        assert "compositeScore" in item
        # Fixture didn't seed score rows → compositeScore null
        assert item["compositeScore"] is None
