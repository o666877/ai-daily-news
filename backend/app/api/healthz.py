"""GET /api/v1/healthz (T046)."""

from __future__ import annotations

from fastapi import APIRouter

from app import __version__

router = APIRouter(prefix="/api/v1", tags=["health"])


_HEALTHZ_EXAMPLE = {
    "status": "ok",
    "version": "1.0.0",
    "pipeline": {"collector": "up", "summarizer": "up"},
}


def _pipeline_status() -> dict[str, str]:
    """Derive collector/summarizer status. MVP: always 'up'."""
    # Real derivation from last collector/summarizer outcomes deferred to Phase 4+.
    return {"collector": "up", "summarizer": "up"}


@router.get(
    "/healthz",
    response_model=None,
    responses={
        200: {
            "description": "Pipeline health snapshot.",
            "content": {"application/json": {"example": _HEALTHZ_EXAMPLE}},
        }
    },
    summary="健康检查",
    description="联调与监控探针；不展示给终端用户。详见 `contracts/healthz.md`。",
)
async def healthz() -> dict:
    """Return {status, version, pipeline:{collector,summarizer}}."""
    pipeline = _pipeline_status()
    both_up = pipeline["collector"] == "up" and pipeline["summarizer"] == "up"
    any_up = pipeline["collector"] == "up" or pipeline["summarizer"] == "up"
    status = "ok" if both_up else ("degraded" if any_up else "down")
    return {"status": status, "version": __version__, "pipeline": pipeline}


__all__ = ["router"]
