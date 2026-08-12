"""T024: Contract test for GET /healthz."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_healthz_status_ok(client: AsyncClient):
    res = await client.get("/api/v1/healthz")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert body["pipeline"]["collector"] == "up"
    assert body["pipeline"]["summarizer"] == "up"
