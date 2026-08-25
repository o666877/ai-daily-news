"""T066: SettingsService — read/write singleton preferences.

`effective_at` is computed as the next calendar day in Asia/Shanghai (UTC+8)
regardless of the host TZ — the daily issue batches run at 00:00 CST.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.errors import ValidationError as BizValidationError
from app.models.meta import SOURCE_KEYS, TYPE_KEYS
from app.models.settings import (
    DailyPush,
    ImPush,
    ImPushWebhook,
    SettingsIn,
    SettingsORM,
    SettingsOut,
    default_settings,
    mask_webhook_url,
    merged_bool_map,
    resolve_im_push,
)

SHANGHAI_TZ = timezone(timedelta(hours=8))


def compute_effective_at(now: datetime | None = None) -> str:
    """Return next calendar day (Asia/Shanghai) as YYYYMMDD string."""
    base = (now or datetime.now(SHANGHAI_TZ)).astimezone(SHANGHAI_TZ)
    next_day = base + timedelta(days=1)
    return next_day.strftime("%Y%m%d")


def _masked_im_push(raw: dict | None) -> ImPush:
    """Stored im_push → output model with webhook urls masked (specs/006)."""
    im = ImPush.model_validate(dict(raw or {}))
    masked = [
        ImPushWebhook(name=w.name, url=mask_webhook_url(w.url)) for w in im.webhooks
    ]
    return im.model_copy(update={"webhooks": masked})


def _row_to_out(orm: SettingsORM) -> SettingsOut:
    dp = dict(orm.daily_push or {})
    return SettingsOut(
        sources=merged_bool_map(orm.sources, SOURCE_KEYS),
        types=merged_bool_map(orm.types, TYPE_KEYS),
        dailyPush=DailyPush(
            enabled=bool(dp.get("enabled", True)),
            time=str(dp.get("time", "08:00")),
        ),
        dailyCount=orm.daily_count,
        imPush=_masked_im_push(orm.im_push),
        updatedAt=orm.updated_at.isoformat() + "Z" if orm.updated_at else None,
    )


class SettingsService:
    """Stateless service backed by a single async session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _get_row(self) -> SettingsORM:
        """Fetch the single settings row; auto-init with defaults if missing."""
        result = await self._session.execute(
            select(SettingsORM).where(SettingsORM.id == 1)
        )
        orm = result.scalar_one_or_none()
        if orm is None:
            defaults = default_settings()
            orm = SettingsORM(
                id=1,
                sources=defaults["sources"],
                types=defaults["types"],
                daily_push=defaults["daily_push"],
                im_push=defaults["im_push"],
                daily_count=defaults["daily_count"],
                updated_at=None,
            )
            self._session.add(orm)
            await self._session.flush()
        return orm

    async def get(self) -> SettingsOut:
        orm = await self._get_row()
        return _row_to_out(orm)

    async def save(self, payload: SettingsIn) -> tuple[SettingsOut, str]:
        orm = await self._get_row()
        orm.sources = dict(payload.sources)
        orm.types = dict(payload.types)
        orm.daily_push = {
            "enabled": payload.dailyPush.enabled,
            "time": payload.dailyPush.time,
        }
        orm.daily_count = payload.dailyCount
        try:
            orm.im_push = resolve_im_push(payload.imPush, orm.im_push)
        except ValueError as exc:
            raise BizValidationError(str(exc)) from exc
        orm.updated_at = datetime.utcnow()
        await self._session.flush()
        await self._session.commit()
        return _row_to_out(orm), compute_effective_at()

    async def reset(self) -> tuple[SettingsOut, str]:
        orm = await self._get_row()
        defaults = default_settings()
        orm.sources = defaults["sources"]
        orm.types = defaults["types"]
        orm.daily_push = defaults["daily_push"]
        orm.im_push = defaults["im_push"]
        orm.daily_count = defaults["daily_count"]
        orm.updated_at = datetime.utcnow()
        await self._session.flush()
        await self._session.commit()
        return _row_to_out(orm), compute_effective_at()

    async def get_current_filters(self) -> tuple[list[str], list[str]]:
        """Return keys where bool value is True (used by pipeline)."""
        orm = await self._get_row()
        sources = [k for k, v in merged_bool_map(orm.sources, SOURCE_KEYS).items() if v]
        types = [k for k, v in merged_bool_map(orm.types, TYPE_KEYS).items() if v]
        return sources, types

    async def get_im_push_raw(self) -> dict:
        """Stored im_push dict with FULL webhook urls (specs/006).

        Caller-side secret: never log, never echo into API responses.
        Deep copy so callers can't mutate the ORM-cached state.
        """
        orm = await self._get_row()
        return copy.deepcopy(dict(orm.im_push or {}))


__all__ = ["SettingsService", "compute_effective_at"]
