"""T066: SettingsService — read/write singleton preferences.

`effective_at` is computed as the next calendar day in Asia/Shanghai (UTC+8)
regardless of the host TZ — the daily issue batches run at 00:00 CST.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.meta import SOURCE_KEYS, TYPE_KEYS
from app.models.settings import (
    DailyPush,
    SettingsIn,
    SettingsORM,
    SettingsOut,
    default_settings,
)


SHANGHAI_TZ = timezone(timedelta(hours=8))


def compute_effective_at(now: datetime | None = None) -> str:
    """Return next calendar day (Asia/Shanghai) as YYYYMMDD string."""
    base = (now or datetime.now(SHANGHAI_TZ)).astimezone(SHANGHAI_TZ)
    next_day = base + timedelta(days=1)
    return next_day.strftime("%Y%m%d")


def _row_to_out(orm: SettingsORM) -> SettingsOut:
    sources = dict(orm.sources or {})
    types = dict(orm.types or {})
    dp = dict(orm.daily_push or {})
    return SettingsOut(
        sources={k: bool(v) for k, v in sources.items()},
        types={k: bool(v) for k, v in types.items()},
        dailyPush=DailyPush(
            enabled=bool(dp.get("enabled", True)),
            time=str(dp.get("time", "08:00")),
        ),
        dailyCount=orm.daily_count,
        styleMode=orm.style_mode,
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
                daily_count=defaults["daily_count"],
                style_mode=defaults["style_mode"],
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
        orm.style_mode = payload.styleMode
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
        orm.daily_count = defaults["daily_count"]
        orm.style_mode = defaults["style_mode"]
        orm.updated_at = datetime.utcnow()
        await self._session.flush()
        await self._session.commit()
        return _row_to_out(orm), compute_effective_at()

    async def get_current_filters(self) -> tuple[list[str], list[str]]:
        """Return keys where bool value is True (used by pipeline)."""
        orm = await self._get_row()
        sources = [k for k in SOURCE_KEYS if bool((orm.sources or {}).get(k))]
        types = [k for k in TYPE_KEYS if bool((orm.types or {}).get(k))]
        return sources, types


__all__ = ["SettingsService", "compute_effective_at"]