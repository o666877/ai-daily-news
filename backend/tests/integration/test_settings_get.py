"""T061: Contract test for GET /api/v1/settings."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


AUTH = {"Authorization": "Bearer test-bearer-token"}

EXPECTED_SOURCE_KEYS = {"x", "github", "reddit", "web"}
EXPECTED_TYPE_KEYS = {"agent", "self_improve", "open_source", "tools", "commentary"}


@pytest.mark.asyncio
async def test_get_settings_returns_default_payload(client: AsyncClient):
    res = await client.get("/api/v1/settings", headers=AUTH)
    assert res.status_code == 200, res.text
    body = res.json()

    # 4 source keys + 5 type keys
    assert set(body["sources"].keys()) == EXPECTED_SOURCE_KEYS
    assert set(body["types"].keys()) == EXPECTED_TYPE_KEYS
    # All bool values (default-on)
    for v in body["sources"].values():
        assert isinstance(v, bool)
    for v in body["types"].values():
        assert isinstance(v, bool)

    # dailyPush block
    assert "dailyPush" in body
    assert set(body["dailyPush"].keys()) == {"enabled", "time"}
    assert isinstance(body["dailyPush"]["enabled"], bool)
    assert body["dailyPush"]["time"] == "08:00"

    # updatedAt present (string or null after init)
    assert "updatedAt" in body


@pytest.mark.asyncio
async def test_get_settings_without_auth_returns_1003(client: AsyncClient):
    """No Bearer token → 401 with business code 1003."""
    res = await client.get("/api/v1/settings")
    assert res.status_code == 401, res.text
    body = res.json()
    assert body["code"] == 1003


@pytest.mark.asyncio
async def test_get_settings_with_invalid_token_returns_1003(client: AsyncClient):
    res = await client.get("/api/v1/settings", headers={"Authorization": "Bearer wrong"})
    assert res.status_code == 401, res.text
    body = res.json()
    assert body["code"] == 1003


# ---------------------------------------------------------------------------
# T027 (US2): response includes dailyCount. styleMode was removed
# (reading-density feature dropped; frontend renders a fixed layout).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_settings_includes_daily_count_default_15(client: AsyncClient) -> None:
    res = await client.get("/api/v1/settings", headers=AUTH)
    assert res.status_code == 200, res.text
    body = res.json()
    assert "dailyCount" in body
    assert body["dailyCount"] == 15  # default (changed from 30 → 8 → 15)
    assert "styleMode" not in body


@pytest.mark.asyncio
async def test_get_settings_reflects_put_daily_count_change(client: AsyncClient) -> None:
    put_body = {
        "sources": {"x": True, "github": False, "reddit": True, "web": True},
        "types": {"agent": True, "self_improve": True, "open_source": False, "tools": True, "commentary": True},
        "dailyPush": {"enabled": True, "time": "09:30"},
        "dailyCount": 10,
    }
    put_res = await client.put("/api/v1/settings", json=put_body, headers=AUTH)
    assert put_res.status_code == 200, put_res.text

    get_res = await client.get("/api/v1/settings", headers=AUTH)
    assert get_res.status_code == 200
    body = get_res.json()
    assert body["dailyCount"] == 10