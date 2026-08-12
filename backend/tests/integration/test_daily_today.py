"""T021: Contract test for GET /daily/today.

Cases:
- 200 ready issue with issue + summary + articles.
- 404 2002 not generated.
- 409 2003 generating.
- Empty articles (status=ready but 0 items).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.models.article import ArticleORM
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
    # 7 fields per item
    first = body["articles"][0]
    expected_keys = {"id", "title", "excerpt", "type", "src", "time", "readingMinutes"}
    assert set(first.keys()) == expected_keys
    # summary has both byType and bySource with all 4 keys
    assert set(body["summary"]["byType"].keys()) == {
        "agent", "self_improve", "open_source", "tools",
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
