"""GET /api/v1/daily/today."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.db import get_session
from app.models import ArticleListItem, DailyIssue, DailyIssueSummary
from app.services.issue_service import get_today

router = APIRouter(prefix="/api/v1", tags=["daily"])


class DailyTodayResponse(DailyIssue):
    """Wrapper for response model: includes issue + summary + articles."""

    pass


@router.get("/daily/today")
async def daily_today(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Return today's issue + summary + articles list (7-field per item)."""
    issue, summary, articles = await get_today(session)
    return {
        "issue": issue.model_dump(by_alias=True, mode="json"),
        "summary": summary.model_dump(by_alias=True, mode="json"),
        "articles": [a.model_dump(by_alias=True, mode="json") for a in articles],
    }


__all__ = ["router"]
