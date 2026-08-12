"""Settings singleton model (T065 — schema used here for generator's read path).

US1 only reads the settings table to compute the issue's filtersApplied
snapshot; full US3 CRUD lives in Phase 5.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db import Base
from app.models._base import CamelModel
from app.models.meta import SOURCE_KEYS, TYPE_KEYS


class SettingsORM(Base):
    """Singleton row (id=1) for user preferences."""

    __tablename__ = "settings"
    __table_args__ = (CheckConstraint("id = 1", name="settings_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    sources: Mapped[dict] = mapped_column(JSON, default=dict)
    types: Mapped[dict] = mapped_column(JSON, default=dict)
    daily_push: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class DailyPush(CamelModel):
    enabled: bool = True
    time: str = "08:00"


class SettingsOut(CamelModel):
    sources: dict[str, bool]
    types: dict[str, bool]
    dailyPush: DailyPush
    updatedAt: str | None = None


def default_settings() -> dict:
    """Return default settings as a JSON-serializable dict (all-on, 08:00)."""
    return {
        "sources": {k: True for k in SOURCE_KEYS},
        "types": {k: True for k in TYPE_KEYS},
        "daily_push": {"enabled": True, "time": "08:00"},
    }


__all__ = ["DailyPush", "SettingsORM", "SettingsOut", "default_settings"]
