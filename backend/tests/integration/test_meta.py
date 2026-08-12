"""T023: Contract test for GET /meta."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_meta_returns_4_sources_4_types(client: AsyncClient):
    res = await client.get("/api/v1/meta")
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["sources"]) == 4
    assert len(body["types"]) == 4
    source_keys = {s["key"] for s in body["sources"]}
    assert source_keys == {"x", "github", "reddit", "web"}
    type_keys = {t["key"] for t in body["types"]}
    assert type_keys == {"agent", "self_improve", "open_source", "tools"}
    # Verify Source fields
    first_src = body["sources"][0]
    assert {"key", "name", "short", "icon", "description"}.issubset(first_src.keys())
    # Verify Type fields
    first_type = body["types"][0]
    assert {"key", "name", "shortName"}.issubset(first_type.keys())
    # Icons must be one of the 4 supported keys
    valid_icons = {"x", "github", "reddit", "globe"}
    for s in body["sources"]:
        assert s["icon"] in valid_icons
