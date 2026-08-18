"""T067-T069: Settings endpoints.

GET   /api/v1/settings         — read current preferences (require_auth)
PUT   /api/v1/settings         — overwrite preferences (require_auth + write_limiter)
POST  /api/v1/settings/reset   — reset to defaults (require_auth + write_limiter)

All write endpoints include `X-Effective-At: YYYYMMDD` response header
indicating the next calendar day (Asia/Shanghai) on which the new settings
will take effect.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.auth import require_auth
from app.infra.db import get_session
from app.infra.errors import ValidationError as BizValidationError
from app.infra.ratelimit import write_limiter
from app.models.settings import SettingsIn
from app.services.settings_service import SettingsService


router = APIRouter(prefix="/api/v1", tags=["settings"])


_SETTINGS_EXAMPLE = {
    "sources": {"x": True, "github": True, "reddit": True, "web": True},
    "types": {
        "agent": True,
        "self_improve": True,
        "open_source": True,
        "tools": True,
    },
    "dailyPush": {"enabled": True, "time": "08:00"},
    "updatedAt": "2026-08-12T10:30:00+08:00",
}


def _service(session: AsyncSession = Depends(get_session)) -> SettingsService:
    return SettingsService(session)


@router.get(
    "/settings",
    response_model=None,
    responses={
        200: {
            "description": "Current user preferences.",
            "content": {"application/json": {"example": _SETTINGS_EXAMPLE}},
        },
        401: {
            "description": "1003 — 未认证",
            "content": {
                "application/json": {
                    "example": {"code": 1003, "message": "未认证", "requestId": "req_abc"}
                }
            },
        },
    },
    summary="获取用户偏好",
    description="设置面板回填；首次访问返回默认值。详见 `contracts/settings-get.md`。",
)
async def get_settings(
    request: Request,
    _user: dict = Depends(require_auth),
    service: SettingsService = Depends(_service),
) -> JSONResponse:
    """Return the singleton settings row (auto-init with defaults if missing)."""
    out = await service.get()
    body = out.model_dump(by_alias=True, mode="json")
    return JSONResponse(content=body)


@router.put(
    "/settings",
    response_model=None,
    responses={
        200: {
            "description": "Saved preferences; response carries X-Effective-At header.",
            "headers": {
                "X-Effective-At": {
                    "description": "生效刊期 YYYYMMDD",
                    "schema": {"type": "string"},
                }
            },
            "content": {"application/json": {"example": _SETTINGS_EXAMPLE}},
        },
        422: {
            "description": "1005 — body 校验失败",
            "content": {
                "application/json": {
                    "example": {"code": 1005, "message": "dailyPush.time 非法", "requestId": "req_abc"}
                }
            },
        },
    },
    summary="保存用户偏好（全量覆盖）",
    description="所有字段必须提交；下一期刊期生成立即生效。详见 `contracts/settings-put.md`。",
)
@write_limiter.limit("30/minute")
async def put_settings(
    request: Request,
    payload: dict,
    _user: dict = Depends(require_auth),
    service: SettingsService = Depends(_service),
) -> JSONResponse:
    """Replace preferences; returns 1005 on validation failure."""
    try:
        validated = SettingsIn.model_validate(payload)
    except ValidationError as exc:
        msg = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        ) or "请求体校验失败"
        raise BizValidationError(msg) from exc

    out, eff = await service.save(validated)
    _sync_scheduler_push(out)
    body = out.model_dump(by_alias=True, mode="json")
    response = JSONResponse(content=body)
    response.headers["X-Effective-At"] = eff
    return response


@router.post(
    "/settings/reset",
    response_model=None,
    responses={
        200: {
            "description": "Reset preferences to defaults (all-on, 08:00).",
            "content": {"application/json": {"example": _SETTINGS_EXAMPLE}},
        },
    },
    summary="恢复默认偏好",
    description="一键回到全开 + 08:00 推送；下一期生效。详见 `contracts/settings-reset.md`。",
)
@write_limiter.limit("30/minute")
async def reset_settings(
    request: Request,
    _user: dict = Depends(require_auth),
    service: SettingsService = Depends(_service),
) -> JSONResponse:
    """Reset preferences to all-on, 08:00."""
    out, eff = await service.reset()
    _sync_scheduler_push(out)
    body = out.model_dump(by_alias=True, mode="json")
    response = JSONResponse(content=body)
    response.headers["X-Effective-At"] = eff
    return response


def _sync_scheduler_push(out: SettingsOut) -> None:
    """Re-register the daily cron from the just-saved dailyPush settings.

    Best-effort: apply_push_schedule is a no-op unless the scheduler is
    running (tests boot the app with a noop lifespan).
    """
    try:
        from app.infra.scheduler import apply_push_schedule

        apply_push_schedule(out.dailyPush.enabled, out.dailyPush.time)
    except Exception:  # pragma: no cover - scheduler is best-effort
        pass


__all__ = ["router"]
