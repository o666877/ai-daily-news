"""DailyIssue entity: ORM + Pydantic schema + IssueStatus enum.

ORM maps to `daily_issues` table.
FiltersApplied is persisted as a JSON column (TEXT in SQLite).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import JSON, DateTime, Enum as SAEnum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db import Base
from app.models._base import CamelModel
from app.models.meta import SourceKey, TypeKey


class IssueStatus(str, Enum):
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"


class FiltersApplied(CamelModel):
    """Snapshot of which sources/types were active for this issue."""

    sources: list[SourceKey]
    types: list[TypeKey]


class DailyIssueSummary(CamelModel):
    """Aggregation counts for daily/today response."""

    byType: dict[str, int]
    bySource: dict[str, int]


# ---------------------------------------------------------------------------
# ORM model
# ---------------------------------------------------------------------------


class DailyIssueORM(Base):
    """SQLAlchemy ORM row for `daily_issues` table."""

    __tablename__ = "daily_issues"

    id: Mapped[str] = mapped_column(String(8), primary_key=True)  # YYYYMMDD
    date: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    edition: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(
        SAEnum(
            "generating", "ready", "failed", name="issue_status"
        ),
        default="generating",
        index=True,
    )
    generated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    filters_applied: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )


# ---------------------------------------------------------------------------
# Pydantic schema
# ---------------------------------------------------------------------------


class DailyIssue(CamelModel):
    """DailyIssue response entity (see contracts/daily-today.md)."""

    id: str
    date: str
    edition: int
    status: IssueStatus
    generatedAt: str | None = None
    articleCount: int = 0
    filtersApplied: FiltersApplied


__all__ = [
    "DailyIssue",
    "DailyIssueORM",
    "DailyIssueSummary",
    "FiltersApplied",
    "IssueStatus",
]
