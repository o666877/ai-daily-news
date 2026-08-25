"""Spec 006 / Ticket 01: settings API 的 im_push 配置契约."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

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
MASKED_URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=****5678"

IM_PUSH = {
    "enabled": True,
    "topN": 5,
    "linkBaseUrl": "https://daily.example.com",
    "webhooks": [{"name": "main", "url": FULL_URL}],
}


def _body(**im_push) -> dict:
    payload = dict(BASE_BODY)
    payload["imPush"] = {**IM_PUSH, **im_push}
    return payload


@pytest.mark.asyncio
async def test_get_settings_returns_im_push_defaults(client: AsyncClient):
    res = await client.get("/api/v1/settings", headers=AUTH)
    assert res.status_code == 200, res.text
    assert res.json()["imPush"] == {
        "enabled": False,
        "topN": 5,
        "linkBaseUrl": "",
        "webhooks": [],
    }


@pytest.mark.asyncio
async def test_put_im_push_persists_and_masks_url(client: AsyncClient):
    res = await client.put("/api/v1/settings", json=_body(), headers=AUTH)
    assert res.status_code == 200, res.text
    im = res.json()["imPush"]
    assert im["enabled"] is True
    assert im["topN"] == 5
    assert im["webhooks"][0]["url"] == MASKED_URL

    res2 = await client.get("/api/v1/settings", headers=AUTH)
    assert res2.json()["imPush"]["webhooks"][0]["url"] == MASKED_URL


@pytest.mark.asyncio
async def test_put_masked_placeholder_preserves_original(
    client: AsyncClient, db_session: AsyncSession
):
    res = await client.put("/api/v1/settings", json=_body(), headers=AUTH)
    assert res.status_code == 200, res.text

    # 回显的脱敏值原样提交:原 webhook 不被破坏
    echo = dict(BASE_BODY)
    echo["imPush"] = {
        "enabled": False,
        "topN": 5,
        "linkBaseUrl": "",
        "webhooks": [{"name": "main", "url": MASKED_URL}],
    }
    res2 = await client.put("/api/v1/settings", json=echo, headers=AUTH)
    assert res2.status_code == 200, res2.text
    assert res2.json()["imPush"]["webhooks"][0]["url"] == MASKED_URL

    # 直查库断言:存储值仍是完整 URL,未被掩码串覆盖
    from sqlalchemy import select

    from app.models.settings import SettingsORM

    orm = (
        await db_session.execute(select(SettingsORM).where(SettingsORM.id == 1))
    ).scalar_one()
    assert orm.im_push["webhooks"][0]["url"] == FULL_URL


@pytest.mark.asyncio
async def test_get_legacy_row_without_im_push_returns_defaults(
    client: AsyncClient, db_session: AsyncSession
):
    # 迁移前存量行:im_push 为 NULL → GET 按默认值返回,不报错
    from sqlalchemy import select

    from app.models.settings import SettingsORM

    orm = (
        await db_session.execute(select(SettingsORM).where(SettingsORM.id == 1))
    ).scalar_one_or_none()
    if orm is None:
        orm = SettingsORM(id=1)
        db_session.add(orm)
    else:
        orm.im_push = None
    await db_session.flush()

    res = await client.get("/api/v1/settings", headers=AUTH)
    assert res.status_code == 200, res.text
    assert res.json()["imPush"]["enabled"] is False
    assert res.json()["imPush"]["webhooks"] == []


@pytest.mark.asyncio
async def test_put_without_im_push_preserves_existing_webhooks(client: AsyncClient):
    res = await client.put("/api/v1/settings", json=_body(), headers=AUTH)
    assert res.status_code == 200, res.text

    # 旧版前端不发送 imPush:已有 webhook 不被清空
    res2 = await client.put("/api/v1/settings", json=dict(BASE_BODY), headers=AUTH)
    assert res2.status_code == 200, res2.text
    res3 = await client.get("/api/v1/settings", headers=AUTH)
    assert res3.json()["imPush"]["webhooks"][0]["url"] == MASKED_URL


@pytest.mark.asyncio
async def test_reset_clears_im_push(client: AsyncClient):
    await client.put("/api/v1/settings", json=_body(), headers=AUTH)
    res = await client.post("/api/v1/settings/reset", headers=AUTH)
    assert res.status_code == 200, res.text
    assert res.json()["imPush"]["webhooks"] == []
    assert res.json()["imPush"]["enabled"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "im_push",
    [
        # 超过 5 个 webhook
        {
            "webhooks": [
                {"name": f"g{i}", "url": FULL_URL} for i in range(6)
            ]
        },
        # 非企微域名
        {"webhooks": [{"name": "main", "url": "https://evil.example.com/send?key=abcd1234efgh5678"}]},
        # name 超长
        {"webhooks": [{"name": "x" * 21, "url": FULL_URL}]},
        # topN 越界
        {"topN": 2},
        {"topN": 11},
        # linkBaseUrl 非法
        {"linkBaseUrl": "notaurl"},
    ],
    ids=["six-webhooks", "bad-domain", "long-name", "top-low", "top-high", "bad-base"],
)
async def test_put_invalid_im_push_returns_422(client: AsyncClient, im_push: dict):
    res = await client.put("/api/v1/settings", json=_body(**im_push), headers=AUTH)
    assert res.status_code == 422, res.text
    assert res.json()["code"] == 1005


@pytest.mark.asyncio
async def test_put_unresolvable_placeholder_returns_422(client: AsyncClient):
    body = _body(
        webhooks=[
            {
                "name": "main",
                "url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=****9999",
            }
        ]
    )
    res = await client.put("/api/v1/settings", json=body, headers=AUTH)
    assert res.status_code == 422, res.text
    assert res.json()["code"] == 1005
