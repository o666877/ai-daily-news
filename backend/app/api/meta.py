"""GET /api/v1/meta (T045)."""

from __future__ import annotations

from fastapi import APIRouter

from app.models import MetaOut, SOURCES, TYPES

router = APIRouter(prefix="/api/v1", tags=["meta"])


@router.get("/meta")
async def get_meta() -> dict:
    """Return 4 sources + 4 types. No DB hit; built from constants."""
    out = MetaOut(sources=SOURCES, types=TYPES)
    return out.model_dump(by_alias=True, mode="json")


__all__ = ["router"]
