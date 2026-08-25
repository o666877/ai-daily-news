"""Settings singleton model (T065 — schema used here for generator's read path).

US1 only reads the settings table to compute the issue's filtersApplied
snapshot; full US3 CRUD lives in Phase 5.
"""

from __future__ import annotations

import copy
import re
from datetime import datetime
from typing import Literal

from pydantic import StrictBool, field_validator, model_validator
from sqlalchemy import JSON, CheckConstraint, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db import Base
from app.models._base import CamelModel
from app.models.meta import SOURCE_KEYS, TYPE_KEYS

DAILY_COUNT_VALUES = (10, 15, 20, 30)

WECOM_WEBHOOK_URL_RE = re.compile(
    r"^https://qyapi\.weixin\.qq\.com/cgi-bin/webhook/send\?key=[0-9A-Za-z-]{8,64}$"
)
WECOM_WEBHOOK_MASKED_RE = re.compile(
    r"^https://qyapi\.weixin\.qq\.com/cgi-bin/webhook/send\?key=\*{4}[0-9A-Za-z-]{0,4}$"
)
WECOM_WEBHOOK_MASK = "****"
MAX_WEBHOOKS = 5


class SettingsORM(Base):
    """Singleton row (id=1) for user preferences."""

    __tablename__ = "settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="settings_singleton"),
        CheckConstraint(
            f"daily_count IN {DAILY_COUNT_VALUES}", name="settings_daily_count_enum"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    sources: Mapped[dict] = mapped_column(JSON, default=dict)
    types: Mapped[dict] = mapped_column(JSON, default=dict)
    daily_push: Mapped[dict] = mapped_column(JSON, default=dict)
    im_push: Mapped[dict] = mapped_column(JSON, default=dict)
    # Runtime default is 15; the database check constraint intentionally accepts only
    # Pydantic-facing values when writing through SettingsIn.
    daily_count: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
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


class ImPushWebhook(CamelModel):
    name: str
    url: str

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not isinstance(v, str) or not 1 <= len(v.strip()) <= 20 or v != v.strip():
            raise ValueError("webhook.name 必须是 1–20 个字符（首尾无空白）")
        return v

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        if is_masked_webhook_url(v):
            return v
        if not isinstance(v, str) or not WECOM_WEBHOOK_URL_RE.fullmatch(v):
            raise ValueError("webhook.url 必须是企业微信群机器人 webhook 地址")
        return v


class ImPush(CamelModel):
    """企业微信推送配置（specs/006）。存库形态与提交形态共用；脱敏占位符
    仅允许出现在提交侧，落库前由 resolve_im_push 回填原值。"""

    enabled: bool = False
    top_n: int = 5
    link_base_url: str = ""
    webhooks: list[ImPushWebhook] = []

    @field_validator("top_n")
    @classmethod
    def _validate_top_n(cls, v: int) -> int:
        if not isinstance(v, int) or not 3 <= v <= 10:
            raise ValueError("imPush.topN 必须在 3–10 之间")
        return v

    @field_validator("link_base_url")
    @classmethod
    def _validate_link_base_url(cls, v: str) -> str:
        if v == "":
            return v
        parsed = re.match(r"^https?://[^\s/$.?#].[^\s]*$", v) if isinstance(v, str) else None
        if parsed is None:
            raise ValueError("imPush.linkBaseUrl 必须是 http(s) URL 或留空")
        return v

    @field_validator("webhooks")
    @classmethod
    def _validate_webhooks(cls, v: list[ImPushWebhook]) -> list[ImPushWebhook]:
        if len(v) > MAX_WEBHOOKS:
            raise ValueError(f"imPush.webhooks 最多 {MAX_WEBHOOKS} 个")
        # name 是推送记录与防重的键,重名会让记录无法区分、防重误判。
        names = [w.name for w in v]
        if len(names) != len(set(names)):
            raise ValueError("imPush.webhooks 存在重复 name,请保持唯一")
        return v


class SettingsOut(CamelModel):
    sources: dict[str, bool]
    types: dict[str, bool]
    dailyPush: DailyPush
    dailyCount: Literal[10, 15, 20, 30] = 15
    imPush: ImPush = ImPush()
    updatedAt: str | None = None


class SettingsIn(CamelModel):
    """Strict input payload (no updatedAt — server-managed).

    imPush 可省略：旧版前端不发送该字段时保留已存的推送配置。
    """

    sources: dict[str, StrictBool]
    types: dict[str, StrictBool]
    dailyPush: DailyPush
    dailyCount: Literal[10, 15, 20, 30]
    imPush: ImPush | None = None

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
        "daily_count": 15,
        "im_push": default_im_push(),
    }


def default_im_push() -> dict:
    """Return default im_push dict (disabled, no webhooks — specs/006)."""
    return {"enabled": False, "top_n": 5, "link_base_url": "", "webhooks": []}


def mask_webhook_url(url: str) -> str:
    """Mask a full wecom webhook URL for display: key → **** + last 4 chars."""
    key = url.split("key=", 1)[1]
    return f"{url[: url.rindex('key=') + 4]}{WECOM_WEBHOOK_MASK}{key[-4:]}"


def is_masked_webhook_url(url: str) -> bool:
    """True if the url is a masked placeholder (**** visible, key hidden)."""
    return isinstance(url, str) and WECOM_WEBHOOK_MASKED_RE.fullmatch(url) is not None


def resolve_im_push(submitted: ImPush | None, existing_raw: dict | None) -> dict:
    """Return the storable im_push dict from a submission.

    Masked placeholder urls (what GET echoed back) are restored to the
    original full url matched from the existing stored config; a placeholder
    that matches nothing raises ValueError — never persist a masked value.
    `submitted=None` means the field was omitted: keep existing as-is.
    """
    if submitted is None:
        return copy.deepcopy(existing_raw or default_im_push())
    existing_hooks = [
        w.get("url", "") for w in dict(existing_raw or {}).get("webhooks", [])
    ]
    resolved_hooks = []
    for hook in submitted.webhooks:
        if not is_masked_webhook_url(hook.url):
            resolved_hooks.append({"name": hook.name, "url": hook.url})
            continue
        matches = [u for u in existing_hooks if mask_webhook_url(u) == hook.url]
        if len(matches) != 1:
            raise ValueError(
                f"webhook.url 占位符无法唯一匹配已存配置"
                f"（尾缀 {hook.url[-4:]}），请重新提交完整地址"
            )
        resolved_hooks.append({"name": hook.name, "url": matches[0]})
    return {
        "enabled": submitted.enabled,
        "top_n": submitted.top_n,
        "link_base_url": submitted.link_base_url,
        "webhooks": resolved_hooks,
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
    "DailyPush",
    "ImPush",
    "ImPushWebhook",
    "MAX_WEBHOOKS",
    "SettingsORM",
    "SettingsOut",
    "SettingsIn",
    "default_im_push",
    "default_settings",
    "is_masked_webhook_url",
    "mask_webhook_url",
    "merged_bool_map",
    "resolve_im_push",
]
