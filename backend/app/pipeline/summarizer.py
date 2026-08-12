"""Summarizer: RawItem → Article with LLM + tenacity retry (T034).

- Max 2 attempts, exponential backoff (1s, 4s) on RateLimitError/APITimeoutError.
- Per-call token logging to llm_calls table (deferred to v2 — we log to JSON for now).
- Daily budget enforcement: raises 9002 (PipelineBusyError) if budget exceeded.

SummarizerFailure raised after retries exhausted; caller marks issue `failed`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import get_settings
from app.infra.errors import PipelineBusyError
from app.infra.llm import LLMClient, LLMProviderError, SummaryResult
from app.models.article import RawItem
from app.models.meta import SourceKey, TypeKey

logger = logging.getLogger("aidaily.summarizer")


class SummarizerFailure(Exception):
    """All retries exhausted; LLM summarization could not complete."""


@dataclass(frozen=True)
class DailySpend:
    """Tracks daily LLM USD spend for budget enforcement."""

    spent_usd: float = 0.0
    call_count: int = 0


# Module-level in-memory spend tracker (resets per process).
_daily_spend: DailySpend = DailySpend()


def reset_daily_spend() -> None:
    global _daily_spend
    _daily_spend = DailySpend()


def get_daily_spend() -> DailySpend:
    return _daily_spend


def _estimate_cost(input_tokens: int, output_tokens: int) -> float:
    """Rough cost estimate: $0.25/MTok input, $1.25/MTok output (Haiku tier)."""
    return (input_tokens * 0.25 + output_tokens * 1.25) / 1_000_000


def check_budget(additional_usd: float = 0.0) -> None:
    """Raise PipelineBusyError (9002) if daily budget would be exceeded."""
    settings = get_settings()
    if _daily_spend.spent_usd + additional_usd > settings.llm_daily_budget_usd:
        raise PipelineBusyError(
            f"日预算超限：已花费 ${_daily_spend.spent_usd:.2f} "
            f"≥ 预算 ${settings.llm_daily_budget_usd:.2f}"
        )


# Tenacity policy: 2 attempts, exp backoff, retry on provider transient errors.
retry_policy = retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type((LLMProviderError,)),
    reraise=True,
)


@retry_policy
async def _summarize_with_retry(
    client: LLMClient, title: str, source: str, raw_text: str
) -> SummaryResult:
    """Inner retryable summarization call."""
    # Check budget before each attempt.
    check_budget()
    return await client.summarize(title, source, raw_text)


async def summarize_item(
    item: RawItem,
    client: LLMClient | None = None,
    *,
    type_hint: TypeKey | None = None,
) -> SummaryResult:
    """Summarize a single RawItem; raise SummarizerFailure if all retries fail."""
    c = client or LLMClient()
    try:
        result = await _summarize_with_retry(c, item.title, item.sourceName, item.rawText)
    except RetryError as exc:  # pragma: no cover defensive
        raise SummarizerFailure(f"summarize failed: {item.sourceUrl}") from exc
    except LLMProviderError as exc:
        raise SummarizerFailure(f"summarize failed: {item.sourceUrl}") from exc
    except PipelineBusyError:
        # Budget exhausted — propagate as 9002 to caller (will mark issue failed).
        raise
    # Approximate cost accounting (Haiku prices; real usage tracked via logging).
    estimated_input = min(len(item.rawText) // 4 + 200, 4000)
    estimated_output = 800
    _track_spend(_estimate_cost(estimated_input, estimated_output))
    return result


def _track_spend(usd: float) -> None:
    global _daily_spend
    _daily_spend = DailySpend(
        spent_usd=_daily_spend.spent_usd + usd,
        call_count=_daily_spend.call_count + 1,
    )


__all__ = [
    "DailySpend",
    "SummarizerFailure",
    "check_budget",
    "get_daily_spend",
    "reset_daily_spend",
    "summarize_item",
]
