"""条目装配器 (article assembly): ArticleORM → Pydantic 的唯一转换点.

specs/004 候选 2. Converges the three hand-rolled ORM→model mappings
(issue_service.get_today, article_service.list_articles,
api/articles detail) into one module. Field-name and score-key mapping
lives here and nowhere else — adding a field means touching this file
plus the contract docs, not N call sites.

Pure from_attributes is not usable: camelCase field names
(readingMinutes/issueId/…) don't match ORM snake_case attributes, and
aliasing every field would pollute the contract models. The explicit
constructors below are the single visible mapping.
"""

from __future__ import annotations

from typing import Any

from app.models.article import Article, ArticleListItem, ArticleORM
from app.models.meta import SourceKey, TypeKey


def _composite(orm: ArticleORM) -> int | None:
    return orm.score.composite_score if orm.score is not None else None


def _score_payload(orm: ArticleORM) -> dict[str, Any] | None:
    """Explicit camelCase score object; None when the article has no score row."""
    score = orm.score
    if score is None:
        return None
    return {
        "compositeScore": score.composite_score,
        "dimensionScores": {
            "authority": score.dim_authority,
            "depth": score.dim_depth,
            "timeliness": score.dim_timeliness,
            "expression": score.dim_expression,
            "engagement": score.dim_engagement,
        },
        "authorityTier": score.authority_tier,
        "scoreSource": score.score_source,
        "topicId": score.topic_id,
        "opinionFingerprint": score.opinion_fingerprint,
    }


def assemble_list_item(orm: ArticleORM) -> ArticleListItem:
    """List/today shape: 7 base fields + compositeScore + mustRead."""
    return ArticleListItem(
        id=orm.id,
        title=orm.title,
        excerpt=orm.excerpt,
        type=TypeKey(orm.type),
        src=SourceKey(orm.src),
        time=orm.time,
        readingMinutes=orm.reading_minutes,
        compositeScore=_composite(orm),
        mustRead=orm.is_must_read,
    )


def assemble_detail(orm: ArticleORM) -> Article:
    """Detail shape: full Article with nested score object (null-safe)."""
    return Article(
        id=orm.id,
        title=orm.title,
        excerpt=orm.excerpt,
        type=TypeKey(orm.type),
        src=SourceKey(orm.src),
        time=orm.time,
        readingMinutes=orm.reading_minutes,
        compositeScore=_composite(orm),
        mustRead=orm.is_must_read,
        issueId=orm.issue_id,
        lede=orm.lede,
        summary=orm.summary,
        body=orm.body,
        quote=orm.quote,
        points=orm.points,
        sourceUrl=orm.source_url,
        sourceName=orm.source_name,
        publishedAt=orm.published_at,
        score=_score_payload(orm),
    )


__all__ = ["assemble_detail", "assemble_list_item"]
