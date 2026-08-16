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


# OpenAPI example (mirrors contracts/daily-today.md).
_DAILY_TODAY_EXAMPLE = {
    "issue": {
        "id": "20260812",
        "date": "2026-08-12",
        "edition": 3,
        "status": "ready",
        "generatedAt": "2026-08-12T08:00:12+08:00",
        "articleCount": 12,
        "filtersApplied": {
            "sources": ["x", "github", "reddit", "web"],
            "types": ["agent", "self_improve", "open_source", "tools"],
        },
    },
    "summary": {
        "byType": {"agent": 3, "self_improve": 3, "open_source": 3, "tools": 3},
        "bySource": {"x": 3, "github": 3, "reddit": 3, "web": 3},
    },
    "articles": [
        {
            "id": "20260812-0001",
            "title": "GPT-5 发布：多模态推理大幅提升",
            "excerpt": "摘要文本…",
            "type": "agent",
            "src": "x",
            "time": "09:12",
            "readingMinutes": 6,
        }
    ],
}


@router.get(
    "/daily/today",
    response_model=None,
    responses={
        200: {
            "description": "Today's issue with summary and article index.",
            "content": {"application/json": {"example": _DAILY_TODAY_EXAMPLE}},
        },
        404: {
            "description": "2002 — 刊期尚未生成",
            "content": {
                "application/json": {
                    "example": {"code": 2002, "message": "今日刊尚未生成", "requestId": "req_abc"}
                }
            },
        },
        409: {
            "description": "2003 — 刊期生成中",
            "content": {
                "application/json": {
                    "example": {"code": 2003, "message": "今日刊正在生成", "requestId": "req_abc"}
                }
            },
        },
    },
    summary="今日刊概览",
    description="首屏一次调用：报头 + 数量徽标 + 索引列表（7 字段/条）。详见 `contracts/daily-today.md`。",
)
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
