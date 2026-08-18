"""Collector orchestrator (T039).

Invoke 4 collectors concurrently via asyncio.gather(return_exceptions=True).
Per-source failures → log warning + return successful items only (FR-007a).
Dedup by normalized source_url.
Classify type via rule-based keywords (deterministic; no LLM cost).
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Awaitable, Callable

from app.models.article import RawItem
from app.models.meta import SourceKey, TypeKey
from app.pipeline.collectors.github import collect_github
from app.pipeline.collectors.reddit import collect_reddit
from app.pipeline.collectors.web import collect_web
from app.pipeline.collectors.x_rsshub import collect_x_rsshub

logger = logging.getLogger("aidaily.collector")

CollectorFn = Callable[[], Awaitable[list[RawItem]]]


# Rule-based classifier keywords per TypeKey.
CLASSIFY_KEYWORDS: dict[TypeKey, list[str]] = {
    TypeKey.AGENT: ["agent", "assistant", "autogen", "react", "tool use", "智能体"],
    TypeKey.SELF_IMPROVE: [
        "self-improv",
        "fine-tune",
        "finetune",
        "sft",
        "rlhf",
        "continuous learning",
        "自我进化",
        "持续学习",
    ],
    TypeKey.OPEN_SOURCE: [
        "github",
        "open source",
        "open-source",
        "mit license",
        "apache 2",
        "release",
        "开源",
    ],
    TypeKey.TOOLS: [
        "tool",
        "library",
        "framework",
        "sdk",
        "plugin",
        "extension",
        "工具",
    ],
}

# Fallback when no keyword hits, keyed by source (specs/005).
_SOURCE_FALLBACK_TYPE: dict[SourceKey, TypeKey] = {
    SourceKey.GITHUB: TypeKey.OPEN_SOURCE,
    SourceKey.X: TypeKey.COMMENTARY,
    SourceKey.REDDIT: TypeKey.COMMENTARY,
    SourceKey.WEB: TypeKey.COMMENTARY,
}


def classify_type(item: RawItem) -> TypeKey:
    """Rule-based type classifier with source-aware fallback (specs/005).

    Keyword hits keep priority. Misses fall back by source: GitHub →
    open_source (repo items are open-source by nature), everything else →
    commentary (the opinion/news catch-all). tools is never a fallback —
    it only ever comes from an explicit keyword hit or LLM verdict.
    """
    text = f"{item.title} {item.rawText}".lower()
    for key, keywords in CLASSIFY_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return key
    return _SOURCE_FALLBACK_TYPE.get(item.sourceKey, TypeKey.COMMENTARY)


def dedup_by_url(items: list[RawItem]) -> list[RawItem]:
    """Remove duplicates by normalized source_url."""
    seen: set[str] = set()
    result: list[RawItem] = []
    for item in items:
        key = _normalize_url(item.sourceUrl)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _normalize_url(url: str) -> str:
    return re.sub(r"[?#].*$", "", url.strip().lower().rstrip("/"))


async def collect_all() -> list[RawItem]:
    """Run all 4 collectors concurrently; return deduplicated, classified items."""
    collectors: list[tuple[str, CollectorFn]] = [
        (SourceKey.X.value, collect_x_rsshub),
        (SourceKey.GITHUB.value, collect_github),
        (SourceKey.REDDIT.value, collect_reddit),
        (SourceKey.WEB.value, collect_web),
    ]
    tasks = [fn() for _, fn in collectors]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)
    all_items: list[RawItem] = []
    for (src_name, _), result in zip(collectors, raw_results, strict=False):
        if isinstance(result, Exception):
            logger.warning(
                "collector_source_failed",
                extra={"source": src_name, "exception_type": type(result).__name__},
            )
            continue
        all_items.extend(result)
    deduped = dedup_by_url(all_items)
    # Classify type for each item.
    return [
        RawItem(
            **{**item.model_dump(by_alias=False), "suggestedType": classify_type(item)}
        )
        for item in deduped
    ]


__all__ = [
    "CLASSIFY_KEYWORDS",
    "classify_type",
    "collect_all",
    "dedup_by_url",
]
