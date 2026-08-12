"""T022: Contract test for GET /articles/{id}.

Cases:
- 200 returns full Article (16 fields).
- 404 2001 not found.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_articles_detail_200_full_fields(
    client: AsyncClient, ready_issue_with_articles
):
    """200 returns all 16 fields per data-model.md §2."""
    res = await client.get("/api/v1/articles/20260812-0001")
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
    }
    assert set(body.keys()) == expected_keys
    assert body["id"] == "20260812-0001"
    assert body["type"] in {"agent", "self_improve", "open_source", "tools"}
    assert body["src"] in {"x", "github", "reddit", "web"}
    assert isinstance(body["body"], list) and len(body["body"]) >= 1
    assert isinstance(body["points"], list) and len(body["points"]) >= 1


@pytest.mark.asyncio
async def test_articles_detail_404_not_found(client: AsyncClient):
    """404 2001 when article id doesn't exist."""
    res = await client.get("/api/v1/articles/nonexistent")
    assert res.status_code == 404, res.text
    body = res.json()
    assert body["code"] == 2001
    assert body["requestId"]
