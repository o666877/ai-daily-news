"""Article entity: ORM + Pydantic schema + RawItem input shape.

ORM maps to `articles` table (see migrations/versions/001_initial.py).
Pydantic:
- `ArticleListItem`: 7 fields (id/title/excerpt/type/src/time/readingMinutes)
- `Article`: full 16 fields (for detail response)
- `RawItem`: pre-LLM item returned by collectors (no lede/summary/body yet)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db import Base
from app.models._base import CamelModel
from app.models.meta import SourceKey, TypeKey


# ---------------------------------------------------------------------------
# ORM model
# ---------------------------------------------------------------------------


class ArticleORM(Base):
    """SQLAlchemy ORM row for `articles` table."""

    __tablename__ = "articles"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    issue_id: Mapped[str] = mapped_column(
        String(8), ForeignKey("daily_issues.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(32), index=True)
    src: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(200))
    excerpt: Mapped[str] = mapped_column(String(200))
    lede: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(String(150))
    body: Mapped[list[str]] = mapped_column(JSON)
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    points: Mapped[list[str]] = mapped_column(JSON)
    time: Mapped[str] = mapped_column(String(5))  # HH:mm
    source_url: Mapped[str] = mapped_column(Text)
    source_name: Mapped[str] = mapped_column(String(200))
    reading_minutes: Mapped[int] = mapped_column(Integer)
    published_at: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class ArticleListItem(CamelModel):
    """7-field list shape for daily/today + articles list responses."""

    id: str
    title: str
    excerpt: str
    type: TypeKey
    src: SourceKey
    time: str
    readingMinutes: int


class Article(ArticleListItem):
    """Full Article: 16 fields for detail endpoint."""

    issueId: str
    lede: str
    summary: str
    body: list[str]
    quote: str | None = None
    points: list[str]
    sourceUrl: str
    sourceName: str
    publishedAt: str


class RawItem(CamelModel):
    """Pre-LLM item returned by collectors. Summarizer fills in LLM fields."""

    sourceKey: SourceKey
    sourceName: str
    sourceUrl: str
    title: str
    rawText: str
    publishedAt: str
    # Optional: collector may suggest a type; classifier overrides if needed.
    suggestedType: TypeKey | None = None
    # Extra metadata for debugging.
    extra: dict[str, Any] | None = None


__all__ = ["Article", "ArticleListItem", "ArticleORM", "RawItem"]
