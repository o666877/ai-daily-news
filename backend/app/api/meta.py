"""GET /api/v1/meta (T045)."""

from __future__ import annotations

from fastapi import APIRouter

from app.models import MetaOut, SOURCES, TYPES

router = APIRouter(prefix="/api/v1", tags=["meta"])


_META_EXAMPLE = {
    "sources": [
        {
            "key": "x",
            "name": "X (Twitter)",
            "short": "X",
            "icon": "x",
            "description": "前沿哨兵，偶尔发疯但信息最快",
        },
        {
            "key": "github",
            "name": "GitHub",
            "short": "GitHub",
            "icon": "github",
            "description": "仓库动态、新项目、趋势榜单",
        },
        {
            "key": "reddit",
            "name": "Reddit",
            "short": "Reddit",
            "icon": "reddit",
            "description": "社区热帖与高赞讨论，一手开发者情报",
        },
        {
            "key": "web",
            "name": "全网聚合",
            "short": "全网",
            "icon": "globe",
            "description": "搜索引擎 + RSS 兜底，不放过漏网之鱼",
        },
    ],
    "types": [
        {"key": "agent", "name": "Agent / 智能体", "shortName": "Agent"},
        {"key": "self_improve", "name": "持续学习 / 自我进化", "shortName": "持续学习"},
        {"key": "open_source", "name": "开源项目", "shortName": "开源"},
        {"key": "tools", "name": "工具与效率", "shortName": "工具效率"},
    ],
}


@router.get(
    "/meta",
    response_model=None,
    responses={
        200: {
            "description": "4 sources + 4 types metadata.",
            "content": {"application/json": {"example": _META_EXAMPLE}},
        }
    },
    summary="信息源/类型元数据",
    description="筛选 chips + 设置面板开关列表的数据源；前端不硬编码。详见 `contracts/meta.md`。",
)
async def get_meta() -> dict:
    """Return 4 sources + 4 types. No DB hit; built from constants."""
    out = MetaOut(sources=SOURCES, types=TYPES)
    return out.model_dump(by_alias=True, mode="json")


__all__ = ["router"]
