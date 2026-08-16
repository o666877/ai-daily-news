"""ArticleScoreORM: per-article scoring snapshot for 002 personalization.

1:1 with articles. Composite score + 4 dimension sub-scores + authority tier
+ dedup signals (topic_id / opinion_fingerprint) + score_source (llm vs
rule_fallback). See specs/002-daily-personalization/data-model.md.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.db import Base


_VALID_TIERS = ("official_blog", "authoritative_media", "community")
_VALID_SOURCES = ("llm", "rule_fallback")


class ArticleScoreORM(Base):
    """Scoring snapshot for one article (1:1 with articles)."""

    __tablename__ = "article_scores"
    __table_args__ = (
        CheckConstraint(
            "composite_score BETWEEN 0 AND 100", name="score_composite_range"
        ),
        CheckConstraint(
            "dim_authority BETWEEN 0 AND 100", name="score_dim_authority_range"
        ),
        CheckConstraint("dim_depth BETWEEN 0 AND 100", name="score_dim_depth_range"),
        CheckConstraint(
            "dim_timeliness BETWEEN 0 AND 100", name="score_dim_timeliness_range"
        ),
        CheckConstraint(
            "dim_expression BETWEEN 0 AND 100", name="score_dim_expression_range"
        ),
        CheckConstraint(
            "dim_engagement BETWEEN 0 AND 100", name="score_dim_engagement_range"
        ),
        CheckConstraint(
            f"authority_tier IN {_VALID_TIERS}", name="score_authority_tier_enum"
        ),
        CheckConstraint(
            f"score_source IN {_VALID_SOURCES}", name="score_source_enum"
        ),
        Index(
            "ix_article_scores_composite_score", "composite_score", postgresql_using="btree"
        ),
        Index("ix_article_scores_topic_id", "topic_id"),
        Index("ix_article_scores_opinion_fingerprint", "opinion_fingerprint"),
    )

    article_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True
    )
    composite_score: Mapped[int] = mapped_column(Integer, nullable=False)
    dim_authority: Mapped[int] = mapped_column(Integer, nullable=False)
    dim_depth: Mapped[int] = mapped_column(Integer, nullable=False)
    dim_timeliness: Mapped[int] = mapped_column(Integer, nullable=False)
    dim_expression: Mapped[int] = mapped_column(Integer, nullable=False)
    dim_engagement: Mapped[int] = mapped_column(
        Integer, nullable=False, default=50
    )
    authority_tier: Mapped[str] = mapped_column(String(32), nullable=False)
    topic_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    opinion_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    score_source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="llm"
    )
    computed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    article: Mapped["object"] = relationship(
        "ArticleORM", back_populates="score"
    )


__all__ = ["ArticleScoreORM"]
