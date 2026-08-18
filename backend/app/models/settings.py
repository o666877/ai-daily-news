"""Settings singleton model (T065 — schema used here for generator's read path).

US1 only reads the settings table to compute the issue's filtersApplied
snapshot; full US3 CRUD lives in Phase 5.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import StrictBool, field_validator, model_validator
from sqlalchemy import JSON, CheckConstraint, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db import Base
from app.models._base import CamelModel
from app.models.meta import SOURCE_KEYS, TYPE_KEYS

DAILY_COUNT_VALUES = (8, 10, 20, 30, 40, 50)
STYLE_MODE_VALUES = ("concise", "standard", "detailed")


class SettingsORM(Base):
    """Singleton row (id=1) for user preferences."""

    __tablename__ = "settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="settings_singleton"),
        CheckConstraint(
            f"daily_count IN {DAILY_COUNT_VALUES}", name="settings_daily_count_enum"
        ),
        CheckConstraint(
            f"style_mode IN {STYLE_MODE_VALUES}", name="settings_style_mode_enum"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    sources: Mapped[dict] = mapped_column(JSON, default=dict)
    types: Mapped[dict] = mapped_column(JSON, default=dict)
    daily_push: Mapped[dict] = mapped_column(JSON, default=dict)
    # Runtime default is 8; the database check constraint intentionally accepts only
    # Pydantic-facing values when writing through SettingsIn.
    daily_count: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    style_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="standard"
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class DailyPush(CamelModel):
    enabled: bool = True
    time: str = "08:00"

    @field_validator("time")
    @classmethod
    def _validate_time(cls, v: str) -> str:
        """Validate HH:mm 24h format (00:00 – 23:59)."""
        if not isinstance(v, str) or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
            raise ValueError("dailyPush.time 必须是 HH:mm 24 小时制（00:00 – 23:59）")
        return v


class SettingsOut(CamelModel):
    sources: dict[str, bool]
    types: dict[str, bool]
    dailyPush: DailyPush
    dailyCount: Literal[8, 10, 20, 30, 40, 50] = 8
    styleMode: Literal["concise", "standard", "detailed"] = "standard"
    updatedAt: str | None = None


class SettingsIn(CamelModel):
    """Strict input payload (no updatedAt — server-managed)."""

    sources: dict[str, StrictBool]
    types: dict[str, StrictBool]
    dailyPush: DailyPush
    dailyCount: Literal[8, 10, 20, 30, 40, 50]
    styleMode: Literal["concise", "standard", "detailed"]

    @model_validator(mode="after")
    def _check_keys(self) -> "SettingsIn":
        missing_sources = set(SOURCE_KEYS) - set(self.sources.keys())
        if missing_sources:
            raise ValueError(f"sources 缺少必填键: {sorted(missing_sources)}")
        missing_types = set(TYPE_KEYS) - set(self.types.keys())
        if missing_types:
            raise ValueError(f"types 缺少必填键: {sorted(missing_types)}")
        # Reject extra keys (defensive — keeps stored dict canonical).
        extra_sources = set(self.sources.keys()) - set(SOURCE_KEYS)
        if extra_sources:
            raise ValueError(f"sources 存在未知键: {sorted(extra_sources)}")
        extra_types = set(self.types.keys()) - set(TYPE_KEYS)
        if extra_types:
            raise ValueError(f"types 存在未知键: {sorted(extra_types)}")
        return self


def default_settings() -> dict:
    """Return default settings as a JSON-serializable dict (all-on, 08:00)."""
    return {
        "sources": {k: True for k in SOURCE_KEYS},
        "types": {k: True for k in TYPE_KEYS},
        "daily_push": {"enabled": True, "time": "08:00"},
        "daily_count": 8,
        "style_mode": "standard",
    }


def merged_bool_map(
    saved: dict | None, valid_keys: list[str] | tuple[str, ...]
) -> dict[str, bool]:
    """Saved bool map with missing keys filled True (specs/005).

    Rows saved before a source/type existed lack its key; reading them
    raw treats the new key as disabled, silently filtering all its content.
    Missing → True (new categories default on); unknown keys dropped.
    """
    merged = {k: True for k in valid_keys}
    for k, v in dict(saved or {}).items():
        if k in merged:
            merged[k] = bool(v)
    return merged


__all__ = [
    "DAILY_COUNT_VALUES",
    "STYLE_MODE_VALUES",
    "DailyPush",
    "SettingsORM",
    "SettingsOut",
    "SettingsIn",
    "default_settings",
    "merged_bool_map",
]
