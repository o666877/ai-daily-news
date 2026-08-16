"""T074: Contract test for POST /api/v1/share and GET /share/{shareId}.

Cases:
- 200 returns shareId (shr_<8hex>) + cardUrl pointing to {host}/share/{shareId} + articleTitle snapshot.
- 404 2001 article not found.
- 400 1001 missing articleId in body.
- 401 1003 no Bearer token.
- GET /share/{shareId} public — 200 HTML; 404 if unknown.
"""

from __future__ import annotations

import re

import pytest
from httpx import AsyncClient


AUTH = {"Authorization": "Bearer test-bearer-token"}

SHARE_ID_PATTERN = re.compile(r"^shr_[0-9a-f]{8}$")


@pytest.mark.asyncio
async def test_post_share_200_returns_required_fields(
    client: AsyncClient, ready_issue_with_articles
):
    """Happy path: 200 with shareId, cardUrl, articleTitle snapshot."""
    _issue, articles = ready_issue_with_articles
    res = await client.post(
        "/api/v1/share",
        json={"articleId": articles[0].id},
        headers=AUTH,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body.keys()) == {"shareId", "cardUrl", "articleTitle"}
    assert SHARE_ID_PATTERN.match(body["shareId"]), body["shareId"]
    # cardUrl is a relative URL (frontend renders it as-is) pointing to /share/{shareId}.
    assert body["cardUrl"].endswith(f"/share/{body['shareId']}"), body["cardUrl"]
    # Article title snapshot — copied from Article.title, not the id.
    assert body["articleTitle"] == "Reddit Agent Post"


@pytest.mark.asyncio
async def test_post_share_404_2001_article_not_found(client: AsyncClient):
    """Non-existent articleId → 404 2001."""
    res = await client.post(
        "/api/v1/share",
        json={"articleId": "missing-id"},
        headers=AUTH,
    )
    assert res.status_code == 404, res.text
    body = res.json()
    assert body["code"] == 2001


@pytest.mark.asyncio
async def test_post_share_400_1001_missing_article_id(client: AsyncClient):
    """Empty body → 400 1001 missing articleId."""
    res = await client.post(
        "/api/v1/share",
        json={},
        headers=AUTH,
    )
    assert res.status_code == 400, res.text
    body = res.json()
    assert body["code"] == 1001


@pytest.mark.asyncio
async def test_post_share_401_1003_no_bearer_token(
    client: AsyncClient, ready_issue_with_articles
):
    """No Authorization header → 401 1003."""
    _issue, articles = ready_issue_with_articles
    res = await client.post(
        "/api/v1/share",
        json={"articleId": articles[0].id},
    )
    assert res.status_code == 401, res.text
    body = res.json()
    assert body["code"] == 1003


@pytest.mark.asyncio
async def test_post_share_persists_snapshot(
    client: AsyncClient, db_session, ready_issue_with_articles
):
    """articleTitle is a snapshot — changing Article.title after share does NOT alter card."""
    _issue, articles = ready_issue_with_articles
    from app.models.article import ArticleORM

    res = await client.post(
        "/api/v1/share",
        json={"articleId": articles[0].id},
        headers=AUTH,
    )
    assert res.status_code == 200, res.text
    snap_title = res.json()["articleTitle"]
    assert snap_title == "Reddit Agent Post"

    # Mutate underlying article title; cached snapshot must NOT change.
    row = await db_session.get(ArticleORM, articles[0].id)
    assert row is not None
    row.title = "MUTATED"
    await db_session.commit()

    res2 = await client.get(f"/share/{res.json()['shareId']}")
    assert res2.status_code == 200, res2.text
    assert snap_title in res2.text
    assert "MUTATED" not in res2.text


@pytest.mark.asyncio
async def test_get_share_card_200_html_public(
    client: AsyncClient, ready_issue_with_articles
):
    """Public GET — no auth required, returns minimal HTML with articleTitle + 阅读原文."""
    _issue, articles = ready_issue_with_articles
    res = await client.post(
        "/api/v1/share",
        json={"articleId": articles[0].id},
        headers=AUTH,
    )
    assert res.status_code == 200, res.text
    share_id = res.json()["shareId"]

    res2 = await client.get(f"/share/{share_id}")
    assert res2.status_code == 200, res2.text
    ctype = res2.headers.get("content-type", "")
    assert ctype.startswith("text/html"), ctype
    body = res2.text
    assert "Reddit Agent Post" in body
    assert "阅读原文" in body
    assert "https://reddit.com/r/example/1" in body  # source_url rendered as link


@pytest.mark.asyncio
async def test_get_share_card_404_for_unknown_id(client: AsyncClient):
    """Unknown shareId → 404."""
    res = await client.get("/share/shr_deadbeef")
    assert res.status_code == 404, res.text
