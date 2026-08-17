"""Unit tests for the article assembly module (specs/004 cand 2).

The assembler is the single conversion point from ArticleORM rows to the
API-facing Pydantic shapes (list item + detail with nested score object).
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.models.article import Article, ArticleListItem, ArticleORM
from app.models.article_score import ArticleScoreORM
from app.services.article_assembly import assemble_detail, assemble_list_item


def _orm(**overrides) -> ArticleORM:
    defaults = dict(
        id="20260817-0001",
        issue_id="20260817",
        type="agent",
        src="github",
        title="标题",
        excerpt="摘要",
        lede="导语",
        summary="总结",
        body="**正文** md",
        quote=None,
        points=["要点"],
        time="09:00",
        source_url="https://a.com",
        source_name="a.com",
        reading_minutes=2,
        published_at="2026-08-17T09:00:00+00:00",
        is_must_read=True,
    )
    defaults.update(overrides)
    return ArticleORM(**defaults)


def _score_orm(composite=88) -> ArticleScoreORM:
    return ArticleScoreORM(
        article_id="20260817-0001",
        composite_score=composite,
        dim_authority=90,
        dim_depth=80,
        dim_timeliness=70,
        dim_expression=60,
        dim_engagement=55,
        authority_tier="official_blog",
        topic_id="gpt-5",
        opinion_fingerprint="gpt-5:launch",
        score_source="llm",
        computed_at=datetime.utcnow(),
    )


def test_assemble_list_item_full_fields():
    orm = _orm()
    orm.score = _score_orm()
    item = assemble_list_item(orm)
    assert isinstance(item, ArticleListItem)
    assert item.id == "20260817-0001"
    assert item.compositeScore == 88
    assert item.mustRead is True
    assert item.readingMinutes == 2


def test_assemble_list_item_without_score_composite_null():
    orm = _orm()
    orm.score = None
    item = assemble_list_item(orm)
    assert item.compositeScore is None
    assert item.mustRead is True


def test_assemble_detail_score_object_nine_keys():
    orm = _orm()
    orm.score = _score_orm()
    detail = assemble_detail(orm)
    assert isinstance(detail, Article)
    score = detail.score
    assert score is not None
    assert score["compositeScore"] == 88
    assert score["dimensionScores"] == {
        "authority": 90,
        "depth": 80,
        "timeliness": 70,
        "expression": 60,
        "engagement": 55,
    }
    assert score["authorityTier"] == "official_blog"
    assert score["scoreSource"] == "llm"
    assert score["topicId"] == "gpt-5"
    assert score["opinionFingerprint"] == "gpt-5:launch"


def test_assemble_detail_without_score_null_safe():
    orm = _orm()
    orm.score = None
    detail = assemble_detail(orm)
    assert detail.score is None
    assert detail.compositeScore is None
    assert detail.body == "**正文** md"
    assert detail.mustRead is True
    assert detail.issueId == "20260817"


def test_assemble_detail_json_roundtrip_camel_case():
    orm = _orm()
    orm.score = _score_orm()
    dumped = assemble_detail(orm).model_dump(by_alias=True, mode="json")
    assert set(dumped) == {
        "id", "issueId", "type", "src", "title", "excerpt", "lede",
        "summary", "body", "quote", "points", "time", "sourceUrl",
        "sourceName", "readingMinutes", "publishedAt", "compositeScore",
        "score", "mustRead",
    }
    assert dumped["sourceUrl"] == "https://a.com"
    assert dumped["mustRead"] is True


def test_assemble_list_and_detail_share_must_read_flag():
    """Both shapes read the same persisted flag — no divergence possible."""
    orm = _orm(is_must_read=False)
    orm.score = None
    assert assemble_list_item(orm).mustRead is False
    assert assemble_detail(orm).mustRead is False
