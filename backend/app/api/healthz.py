"""GET /api/v1/healthz (T046)."""

from __future__ import annotations

from fastapi import APIRouter

from app import __version__

router = APIRouter(prefix="/api/v1", tags=["health"])


def _pipeline_status() -> dict[str, str]:
    """Derive collector/summarizer status. MVP: always 'up'."""
    # Real derivation from last collector/summarizer outcomes deferred to Phase 4+.
    return {"collector": "up", "summarizer": "up"}


@router.get("/healthz")
async def healthz() -> dict:
    """Return {status, version, pipeline:{collector,summarizer}}."""
    pipeline = _pipeline_status()
    both_up = pipeline["collector"] == "up" and pipeline["summarizer"] == "up"
    any_up = pipeline["collector"] == "up" or pipeline["summarizer"] == "up"
    status = "ok" if both_up else ("degraded" if any_up else "down")
    return {"status": status, "version": __version__, "pipeline": pipeline}


__all__ = ["router"]
