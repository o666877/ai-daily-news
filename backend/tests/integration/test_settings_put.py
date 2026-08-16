"""T062: Contract test for PUT /api/v1/settings."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient


AUTH = {"Authorization": "Bearer test-bearer-token"}

VALID_BODY = {
    "sources": {"x": True, "github": False, "reddit": True, "web": True},
    "types": {"agent": True, "self_improve": True, "open_source": False, "tools": True},
    "dailyPush": {"enabled": True, "time": "09:30"},
    "dailyCount": 20,
    "styleMode": "standard",
}


def _expected_effective_at() -> str:
    """Next calendar day in Asia/Shanghai (UTC+8) — tests use UTC env but
    next-day is computed in service using fixed TZ shanghai regardless of env."""
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    return (now + timedelta(days=1)).strftime("%Y%m%d")


@pytest.mark.asyncio
async def test_put_settings_returns_x_effective_at_header(client: AsyncClient):
    res = await client.put("/api/v1/settings", json=VALID_BODY, headers=AUTH)
    assert res.status_code == 200, res.text
    assert "x-effective-at" in {k.lower() for k in res.headers.keys()}
    eff = res.headers["x-effective-at"]
    assert re.fullmatch(r"\d{8}", eff), f"expected YYYYMMDD, got {eff}"
    # Should be tomorrow (Asia/Shanghai) — accept either UTC or shanghai tomorrow.
    today_utc = datetime.now(timezone.utc).strftime("%Y%m%d")
    tomorrow_utc = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y%m%d")
    tomorrow_sha = _expected_effective_at()
    assert eff in {tomorrow_utc, tomorrow_sha}


@pytest.mark.asyncio
async def test_put_settings_persists_body(client: AsyncClient):
    res = await client.put("/api/v1/settings", json=VALID_BODY, headers=AUTH)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["sources"]["github"] is False
    assert body["types"]["open_source"] is False
    assert body["dailyPush"]["time"] == "09:30"
    assert body["updatedAt"] is not None

    # GET reflects same state
    res2 = await client.get("/api/v1/settings", headers=AUTH)
    assert res2.status_code == 200
    body2 = res2.json()
    assert body2["sources"] == VALID_BODY["sources"]
    assert body2["types"] == VALID_BODY["types"]
    assert body2["dailyPush"] == VALID_BODY["dailyPush"]


@pytest.mark.asyncio
async def test_put_settings_is_idempotent(client: AsyncClient):
    """FR-022: re-save same body returns same state."""
    res1 = await client.put("/api/v1/settings", json=VALID_BODY, headers=AUTH)
    res2 = await client.put("/api/v1/settings", json=VALID_BODY, headers=AUTH)
    assert res1.status_code == 200
    assert res2.status_code == 200
    assert res1.json()["sources"] == res2.json()["sources"]
    assert res1.json()["types"] == res2.json()["types"]
    assert res1.json()["dailyPush"] == res2.json()["dailyPush"]


@pytest.mark.asyncio
async def test_put_settings_missing_source_key_returns_1005(client: AsyncClient):
    body = {
        "sources": {"x": True, "github": False, "reddit": True},  # missing "web"
        "types": VALID_BODY["types"],
        "dailyPush": VALID_BODY["dailyPush"],
    }
    res = await client.put("/api/v1/settings", json=body, headers=AUTH)
    assert res.status_code == 422, res.text
    assert res.json()["code"] == 1005


@pytest.mark.asyncio
async def test_put_settings_missing_type_key_returns_1005(client: AsyncClient):
    body = {
        "sources": VALID_BODY["sources"],
        "types": {"agent": True, "self_improve": True, "open_source": True},  # missing tools
        "dailyPush": VALID_BODY["dailyPush"],
    }
    res = await client.put("/api/v1/settings", json=body, headers=AUTH)
    assert res.status_code == 422, res.text
    assert res.json()["code"] == 1005


@pytest.mark.asyncio
async def test_put_settings_invalid_time_returns_1005(client: AsyncClient):
    body = {
        "sources": VALID_BODY["sources"],
        "types": VALID_BODY["types"],
        "dailyPush": {"enabled": True, "time": "25:00"},
    }
    res = await client.put("/api/v1/settings", json=body, headers=AUTH)
    assert res.status_code == 422, res.text
    assert res.json()["code"] == 1005


@pytest.mark.asyncio
async def test_put_settings_non_boolean_returns_1005(client: AsyncClient):
    body = {
        "sources": {"x": "yes", "github": False, "reddit": True, "web": True},
        "types": VALID_BODY["types"],
        "dailyPush": VALID_BODY["dailyPush"],
    }
    res = await client.put("/api/v1/settings", json=body, headers=AUTH)
    assert res.status_code == 422, res.text
    assert res.json()["code"] == 1005


@pytest.mark.asyncio
async def test_put_settings_without_auth_returns_1003(client: AsyncClient):
    res = await client.put("/api/v1/settings", json=VALID_BODY)
    assert res.status_code == 401, res.text
    assert res.json()["code"] == 1003


# ---------------------------------------------------------------------------
# T026 (US2): dailyCount validation — must be one of {10,20,30,40,50}.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_value", [15, "30", 30.0, 0, 60, -10, 100])
async def test_put_settings_daily_count_out_of_enum_returns_1005(
    client: AsyncClient, bad_value: object
) -> None:
    body = {
        "sources": VALID_BODY["sources"],
        "types": VALID_BODY["types"],
        "dailyPush": VALID_BODY["dailyPush"],
        "dailyCount": bad_value,
        "styleMode": "standard",
    }
    res = await client.put("/api/v1/settings", json=body, headers=AUTH)
    assert res.status_code == 422, res.text
    assert res.json()["code"] == 1005


@pytest.mark.asyncio
@pytest.mark.parametrize("good_value", [10, 20, 30, 40, 50])
async def test_put_settings_daily_count_valid_returns_echo(
    client: AsyncClient, good_value: int
) -> None:
    body = {
        "sources": VALID_BODY["sources"],
        "types": VALID_BODY["types"],
        "dailyPush": VALID_BODY["dailyPush"],
        "dailyCount": good_value,
        "styleMode": "standard",
    }
    res = await client.put("/api/v1/settings", json=body, headers=AUTH)
    assert res.status_code == 200, res.text
    assert res.json()["dailyCount"] == good_value


@pytest.mark.asyncio
async def test_put_settings_daily_count_missing_returns_1005(client: AsyncClient) -> None:
    body = {
        "sources": VALID_BODY["sources"],
        "types": VALID_BODY["types"],
        "dailyPush": VALID_BODY["dailyPush"],
        "styleMode": "standard",
    }
    res = await client.put("/api/v1/settings", json=body, headers=AUTH)
    assert res.status_code == 422, res.text
    assert res.json()["code"] == 1005