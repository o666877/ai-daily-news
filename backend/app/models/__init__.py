"""Pydantic + SQLAlchemy models package.

Re-export all model classes so `from app import models` works for
metadata registration (init_db) and code access.
"""

from app.models._base import CamelModel
from app.models.article import (
    Article,
    ArticleORM,
    ArticleListItem,
    RawItem,
)
from app.models.daily_issue import (
    DailyIssue,
    DailyIssueORM,
    DailyIssueSummary,
    IssueStatus,
)
from app.models.meta import (
    SOURCE_KEYS,
    TYPE_KEYS,
    SOURCES,
    TYPES,
    MetaOut,
    Source,
    SourceKey,
    Type,
    TypeKey,
)
from app.models.settings import (
    DailyPush,
    SettingsORM,
    SettingsOut,
    default_settings,
)

__all__ = [
    "Article",
    "ArticleListItem",
    "ArticleORM",
    "CamelModel",
    "DailyIssue",
    "DailyIssueORM",
    "DailyIssueSummary",
    "DailyPush",
    "IssueStatus",
    "MetaOut",
    "SOURCES",
    "SOURCE_KEYS",
    "SettingsORM",
    "SettingsOut",
    "Source",
    "SourceKey",
    "TYPES",
    "TYPE_KEYS",
    "Type",
    "TypeKey",
    "RawItem",
    "default_settings",
]
