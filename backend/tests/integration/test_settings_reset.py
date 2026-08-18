"""T063: Contract test for POST /api/v1/settings/reset."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


AUTH = {"Authorization": "Bearer test-bearer-token"}

EXPECTED_SOURCE_KEYS = {"x", "github", "reddit", "web"}
EXPECTED_TYPE_KEYS = {"agent", "self_improve", "open_source", "tools", "commentary"}


@pytest.mark.asyncio
async def test_reset_returns_default_settings(client: AsyncClient):
    res = await client.post("/api/v1/settings/reset", headers=AUTH)
    assert res.status_code == 200, res.text
    body = res.json()

    # 4 source keys + 4 type keys, all true
    assert set(body["sources"].keys()) == EXPECTED_SOURCE_KEYS
    assert set(body["types"].keys()) == EXPECTED_TYPE_KEYS
    assert all(body["sources"].values()) is True
    assert all(body["types"].values()) is True

    # dailyPush defaults
    assert body["dailyPush"] == {"enabled": True, "time": "08:00"}

    # updatedAt present
    assert "updatedAt" in body


@pytest.mark.asyncio
async def test_reset_response_identical_to_first_get(client: AsyncClient):
    """After reset, GET returns identical payload (defaults)."""
    # Mutate first via PUT so reset has visible effect
    custom = {
        "sources": {"x": False, "github": False, "reddit": False, "web": False},
        "types": {"agent": False, "self_improve": False, "open_source": False, "tools": False, "commentary": False},
        "dailyPush": {"enabled": False, "time": "12:34"},
    }
    await client.put("/api/v1/settings", json=custom, headers=AUTH)

    # Reset
    res_reset = await client.post("/api/v1/settings/reset", headers=AUTH)
    assert res_reset.status_code == 200
    reset_body = res_reset.json()

    # Subsequent GET should match
    res_get = await client.get("/api/v1/settings", headers=AUTH)
    assert res_get.status_code == 200
    get_body = res_get.json()

    # Compare core fields (updatedAt may differ by ms; sources/types/dailyPush must match)
    assert reset_body["sources"] == get_body["sources"]
    assert reset_body["types"] == get_body["types"]
    assert reset_body["dailyPush"] == get_body["dailyPush"]
    # And they should equal the defaults
    assert reset_body["sources"] == {k: True for k in EXPECTED_SOURCE_KEYS}
    assert reset_body["types"] == {k: True for k in EXPECTED_TYPE_KEYS}
    assert reset_body["dailyPush"] == {"enabled": True, "time": "08:00"}


@pytest.mark.asyncio
async def test_reset_sets_x_effective_at_header(client: AsyncClient):
    res = await client.post("/api/v1/settings/reset", headers=AUTH)
    assert res.status_code == 200
    assert "x-effective-at" in {k.lower() for k in res.headers.keys()}
    import re as _re

    assert _re.fullmatch(r"\d{8}", res.headers["x-effective-at"])


@pytest.mark.asyncio
async def test_reset_without_auth_returns_1003(client: AsyncClient):
    res = await client.post("/api/v1/settings/reset")
    assert res.status_code == 401, res.text
    assert res.json()["code"] == 1003