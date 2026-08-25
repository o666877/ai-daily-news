"""Spec 006 / Ticket 04: 手动重推 + 推送状态端点契约."""

from __future__ import annotations

import httpx
import pytest
import respx
from httpx import AsyncClient
from sqlalchemy import select

from app.infra.db import get_session_factory
from app.models.im_push_log import ImPushLogORM

AUTH = {"Authorization": "Bearer test-bearer-token"}

URL_A = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abcd1234efgh5678"
URL_B = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=wxyz9876abcd4321"

BASE_BODY = {
    "sources": {"x": True, "github": True, "reddit": True, "web": True},
    "types": {
        "agent": True,
        "self_improve": True,
        "open_source": True,
        "tools": True,
        "commentary": True,
    },
    "dailyPush": {"enabled": True, "time": "08:00"},
    "dailyCount": 15,
}


def _im_push_body(**im) -> dict:
    body = dict(BASE_BODY)
    body["imPush"] = {
        "enabled": True,
        "topN": 5,
        "linkBaseUrl": "",
        "webhooks": [
            {"name": "good", "url": URL_A},
            {"name": "bad", "url": URL_B},
        ],
        **im,
    }
    return body


def _today_id() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y%m%d")


async def _log_count() -> int:
    factory = get_session_factory()
    async with factory() as s:
        rows = (await s.execute(select(ImPushLogORM))).scalars().all()
        return len(rows)


@pytest.mark.asyncio
@respx.mock
async def test_repush_bypasses_dedup_and_logs(
    client: AsyncClient, ready_issue_with_articles
):
    res = await client.put("/api/v1/settings", json=_im_push_body(), headers=AUTH)
    assert res.status_code == 200, res.text
    ok_route = respx.post(URL_A).mock(
        return_value=httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})
    )
    respx.post(URL_B).mock(return_value=httpx.Response(500, text="down"))

    issue_id = _today_id()
    res = await client.post(f"/api/v1/daily/issues/{issue_id}/im-push", headers=AUTH)
    assert res.status_code == 200, res.text
    body = res.json()
    by_name = {r["name"]: r for r in body["results"]}
    assert by_name["good"]["ok"] is True
    assert by_name["bad"]["ok"] is False
    assert ok_route.call_count == 1  # bad 走满重试不阻塞 good
    assert await _log_count() == 2

    # 重推绕过防重:再推一次,记录与调用都增加
    res2 = await client.post(f"/api/v1/daily/issues/{issue_id}/im-push", headers=AUTH)
    assert res2.status_code == 200, res2.text
    assert ok_route.call_count == 2
    assert await _log_count() == 4


@pytest.mark.asyncio
@respx.mock
async def test_status_lists_latest_per_webhook(
    client: AsyncClient, ready_issue_with_articles
):
    res = await client.put("/api/v1/settings", json=_im_push_body(), headers=AUTH)
    assert res.status_code == 200, res.text

    issue_id = _today_id()
    res = await client.get(f"/api/v1/daily/issues/{issue_id}/im-push", headers=AUTH)
    assert res.status_code == 200, res.text
    statuses = {s["name"]: s for s in res.json()["statuses"]}
    assert set(statuses) == {"good", "bad"}
    assert statuses["good"]["pushed"] is False  # 尚无任何记录

    respx.post(URL_A).mock(
        return_value=httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})
    )
    respx.post(URL_B).mock(return_value=httpx.Response(500, text="down"))
    await client.post(f"/api/v1/daily/issues/{issue_id}/im-push", headers=AUTH)

    res2 = await client.get(f"/api/v1/daily/issues/{issue_id}/im-push", headers=AUTH)
    statuses2 = {s["name"]: s for s in res2.json()["statuses"]}
    assert statuses2["good"]["pushed"] is True
    assert statuses2["good"]["ok"] is True
    assert statuses2["bad"]["pushed"] is True
    assert statuses2["bad"]["ok"] is False
    assert statuses2["good"]["pushedAt"]


@pytest.mark.asyncio
async def test_repush_missing_issue_returns_2002(client: AsyncClient):
    res = await client.put("/api/v1/settings", json=_im_push_body(), headers=AUTH)
    assert res.status_code == 200, res.text
    res = await client.post("/api/v1/daily/issues/20990101/im-push", headers=AUTH)
    assert res.status_code == 404, res.text
    assert res.json()["code"] == 2002


@pytest.mark.asyncio
async def test_repush_without_webhooks_returns_2004(
    client: AsyncClient, ready_issue_with_articles
):
    body = dict(BASE_BODY)
    body["imPush"] = {"enabled": True, "topN": 5, "linkBaseUrl": "", "webhooks": []}
    res = await client.put("/api/v1/settings", json=body, headers=AUTH)
    assert res.status_code == 200, res.text

    issue_id = _today_id()
    res = await client.post(f"/api/v1/daily/issues/{issue_id}/im-push", headers=AUTH)
    assert res.status_code == 404, res.text
    assert res.json()["code"] == 2004


@pytest.mark.asyncio
async def test_status_missing_issue_returns_2002(client: AsyncClient):
    res = await client.get("/api/v1/daily/issues/20990101/im-push", headers=AUTH)
    assert res.status_code == 404, res.text
    assert res.json()["code"] == 2002


@pytest.mark.asyncio
async def test_repush_requires_auth(client: AsyncClient):
    res = await client.post("/api/v1/daily/issues/20260825/im-push")
    assert res.status_code == 401, res.text


@pytest.mark.asyncio
async def test_status_requires_auth(client: AsyncClient):
    res = await client.get("/api/v1/daily/issues/20260825/im-push")
    assert res.status_code == 401, res.text
