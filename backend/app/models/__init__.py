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
from app.models.article_score import ArticleScoreORM
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
    DAILY_COUNT_VALUES,
    STYLE_MODE_VALUES,
    DailyPush,
    SettingsIn,
    SettingsORM,
    SettingsOut,
    default_settings,
)
from app.models.share_card import ShareCardORM, ShareCardOut

__all__ = [
    "Article",
    "ArticleListItem",
    "ArticleORM",
    "ArticleScoreORM",
    "CamelModel",
    "DAILY_COUNT_VALUES",
    "DailyIssue",
    "DailyIssueORM",
    "DailyIssueSummary",
    "DailyPush",
    "IssueStatus",
    "MetaOut",
    "SOURCES",
    "SOURCE_KEYS",
    "STYLE_MODE_VALUES",
    "SettingsIn",
    "SettingsORM",
    "SettingsOut",
    "ShareCardORM",
    "ShareCardOut",
    "Source",
    "SourceKey",
    "TYPES",
    "TYPE_KEYS",
    "Type",
    "TypeKey",
    "RawItem",
    "default_settings",
]
