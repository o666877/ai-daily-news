"""Article entity: ORM + Pydantic schema + RawItem input shape.

ORM maps to `articles` table (see migrations/versions/001_initial.py).
Pydantic:
- `ArticleListItem`: 7 fields (id/title/excerpt/type/src/time/readingMinutes)
- `Article`: full 16 fields (for detail response)
- `RawItem`: pre-LLM item returned by collectors (no lede/summary/body yet)
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.db import Base
from app.models._base import CamelModel
from app.models.meta import SourceKey, TypeKey

if TYPE_CHECKING:
    from app.models.article_score import ArticleScoreORM


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
    body: Mapped[str] = mapped_column(Text)
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    points: Mapped[list[str]] = mapped_column(JSON)
    time: Mapped[str] = mapped_column(String(5))  # HH:mm
    source_url: Mapped[str] = mapped_column(Text)
    source_name: Mapped[str] = mapped_column(String(200))
    reading_minutes: Mapped[int] = mapped_column(Integer)
    published_at: Mapped[str] = mapped_column(String(40))
    # Editorial top-N pick flag, set once at generation time from the
    # persistence index (specs/004 candidate 1). The single source of truth
    # for mustRead on every read path.
    is_must_read: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )

    score: Mapped["ArticleScoreORM | None"] = relationship(
        "ArticleScoreORM",
        back_populates="article",
        cascade="all, delete-orphan",
        uselist=False,
    )


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class ArticleListItem(CamelModel):
    """7-field list shape for daily/today + articles list responses.

    US1: compositeScore (int | null) added — null for legacy rows lacking a
    score row.
    """

    id: str
    title: str
    excerpt: str
    type: TypeKey
    src: SourceKey
    time: str
    readingMinutes: int
    # Full publish timestamp (source item's original date); lets clients
    # render a real date instead of the bare HH:mm `time` column.
    publishedAt: str = ""
    compositeScore: int | None = None
    # True for the issue's editorial top-3, persisted at generation time
    # (articles.is_must_read). Stable across filter views — clients must
    # not recompute it from list position or id suffix.
    mustRead: bool = False


class Article(ArticleListItem):
    """Full Article: 16 fields for detail endpoint.

    US1: score sub-object added (compositeScore + 4 dimensionScores +
    authorityTier + scoreSource + topicId + opinionFingerprint).
    """

    issueId: str
    lede: str
    summary: str
    # Markdown string (specs/002): paragraphs, bold, inline code, links,
    # bullet lists, quotes. Rendered client-side with a sanitized pipeline.
    body: str
    quote: str | None = None
    points: list[str]
    sourceUrl: str
    sourceName: str
    publishedAt: str
    score: dict[str, Any] | None = None


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
