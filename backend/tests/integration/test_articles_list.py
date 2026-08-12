"""T052: Contract tests for GET /api/v1/articles list filtering."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


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
