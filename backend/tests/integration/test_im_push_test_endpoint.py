"""Spec 006 / Ticket 02: POST /api/v1/settings/im-push/test 契约."""

from __future__ import annotations

import httpx
import pytest
import respx
from httpx import AsyncClient

AUTH = {"Authorization": "Bearer test-bearer-token"}

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

FULL_URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abcd1234efgh5678"


async def _seed_webhook(client: AsyncClient, name: str = "main") -> None:
    body = dict(BASE_BODY)
    body["imPush"] = {
        "enabled": True,
        "topN": 5,
        "linkBaseUrl": "",
        "webhooks": [{"name": name, "url": FULL_URL}],
    }
    res = await client.put("/api/v1/settings", json=body, headers=AUTH)
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
@respx.mock
async def test_send_test_message_success(client: AsyncClient):
    await _seed_webhook(client)
    route = respx.post(FULL_URL).mock(
        return_value=httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})
    )
    res = await client.post(
        "/api/v1/settings/im-push/test", json={"name": "main"}, headers=AUTH
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["name"] == "main"
    assert route.call_count == 1
    import json as _json

    sent = _json.loads(route.calls.last.request.content.decode("utf-8"))
    assert "测试" in sent["markdown"]["content"]


@pytest.mark.asyncio
@respx.mock
async def test_send_test_message_wecom_failure_returns_ok_false(client: AsyncClient):
    await _seed_webhook(client)
    respx.post(FULL_URL).mock(
        return_value=httpx.Response(200, json={"errcode": 93000, "errmsg": "invalid webhook"})
    )
    res = await client.post(
        "/api/v1/settings/im-push/test", json={"name": "main"}, headers=AUTH
    )
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is False
    assert res.json()["errcode"] == 93000


@pytest.mark.asyncio
async def test_unknown_webhook_name_returns_business_error(client: AsyncClient):
    await _seed_webhook(client)
    res = await client.post(
        "/api/v1/settings/im-push/test", json={"name": "nope"}, headers=AUTH
    )
    assert res.status_code == 404, res.text
    body = res.json()
    assert body["code"] == 2004


@pytest.mark.asyncio
async def test_missing_name_returns_422(client: AsyncClient):
    res = await client.post("/api/v1/settings/im-push/test", json={}, headers=AUTH)
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_requires_auth(client: AsyncClient):
    res = await client.post("/api/v1/settings/im-push/test", json={"name": "main"})
    assert res.status_code == 401, res.text
    assert res.json()["code"] == 1003


@pytest.mark.asyncio
async def test_no_configured_webhooks_returns_business_error(client: AsyncClient):
    res = await client.post(
        "/api/v1/settings/im-push/test", json={"name": "main"}, headers=AUTH
    )
    assert res.status_code == 404, res.text
    assert res.json()["code"] == 2004
