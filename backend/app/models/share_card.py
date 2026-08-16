"""T075: ShareCard entity — ORM + Pydantic schema.

ORM maps to `share_cards` table (created by migration 001/002).
Pydantic:
- `ShareCardOut`: 3 fields per contracts/share.md (shareId, cardUrl, articleTitle).
- `ShareCardORM`: SQLAlchemy row.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db import Base
from app.models._base import CamelModel


# ---------------------------------------------------------------------------
# ORM model
# ---------------------------------------------------------------------------


class ShareCardORM(Base):
    """SQLAlchemy ORM row for `share_cards` table.

    Each card is an immutable snapshot of `article_title` taken at creation
    time so that subsequent edits to the source Article don't alter what
    visitors of the share page see.
    """

    __tablename__ = "share_cards"

    share_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    article_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("articles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    article_title: Mapped[str] = mapped_column(String(200), nullable=False)
    card_url: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, default=datetime.utcnow
    )


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class ShareCardOut(CamelModel):
    """Response shape for POST /api/v1/share (3 fields per contracts/share.md)."""

    shareId: str
    cardUrl: str
    articleTitle: str


__all__ = ["ShareCardORM", "ShareCardOut"]
