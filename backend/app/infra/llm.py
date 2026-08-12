"""LLM client: Anthropic-compatible adapter (T033).

Wraps the official Anthropic SDK with `base_url`/`api_key`/`model` config so
deployers can point at OneAPI/DeepSeek/Moonshot compatible endpoints.

Returns structured `SummaryResult` via JSON-mode prompt.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

try:
    import anthropic  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    anthropic = None  # type: ignore[assignment]

from app.config import get_settings
from app.infra.errors import PipelineBusyError

logger = logging.getLogger("aidaily.llm")


class LLMProviderError(Exception):
    """Raised when LLM provider call fails after retries."""


@dataclass(frozen=True)
class SummaryResult:
    """Structured summary returned by LLM for a single RawItem."""

    lede: str
    summary: str
    body: list[str]
    quote: str | None
    points: list[str]


SYSTEM_PROMPT = """You are an AI news editor. Summarize the user-provided raw article text into a STRICT JSON object with these exact keys:
- lede (string): a one-paragraph lede, 60-120 Chinese characters, summarizing the news.
- summary (string): a single-sentence takeaway, ≤80 Chinese characters.
- body (string[]): 2-4 paragraph strings of body text.
- quote (string|null): a notable verbatim quote, or null.
- points (string[]): 3-5 bullet-point takeaways, each ≤60 chars.

Return ONLY the JSON object, no markdown, no preamble."""


def _build_prompt(title: str, source: str, raw_text: str) -> str:
    return (
        f"Title: {title}\n"
        f"Source: {source}\n\n"
        f"Raw content:\n{raw_text[:8000]}\n\n"
        "Respond with the JSON object now."
    )


def _parse_summary_response(text: str) -> SummaryResult:
    """Parse LLM JSON response into SummaryResult. Raises LLMProviderError on malformed."""
    # Strip markdown code fences if present.
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = [ln for ln in lines if not ln.startswith("```")]
        text = "\n".join(lines)
    try:
        data: dict[str, Any] = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMProviderError(f"LLM returned non-JSON: {exc}") from exc
    return SummaryResult(
        lede=str(data.get("lede", "")).strip(),
        summary=str(data.get("summary", "")).strip(),
        body=[str(p) for p in data.get("body", []) if str(p).strip()],
        quote=data.get("quote"),
        points=[str(p) for p in data.get("points", []) if str(p).strip()],
    )


class LLMClient:
    """Single Anthropic-compatible client."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        s = get_settings()
        self.base_url = base_url or s.llm_base_url
        self.api_key = api_key or s.llm_api_key or "test-key"
        self.model = model or s.llm_model
        self._client = None
        if anthropic is not None:
            try:
                self._client = anthropic.Anthropic(
                    base_url=self.base_url,
                    api_key=self.api_key,
                    max_retries=0,  # we use tenacity at caller level
                )
            except Exception:  # pragma: no cover - construction rarely fails
                self._client = None

    async def complete_json(self, prompt: str, system: str = SYSTEM_PROMPT) -> str:
        """Call LLM and return raw text response.

        Raises LLMProviderError on transport failures; PipelineBusyError on 429.
        """
        if self._client is None:
            raise LLMProviderError("Anthropic SDK unavailable")
        try:
            # SDK is sync; run in thread executor.
            import asyncio

            def _call() -> str:
                resp = self._client.messages.create(  # type: ignore[union-attr]
                    model=self.model,
                    max_tokens=1200,
                    system=system,
                    messages=[{"role": "user", "content": prompt}],
                )
                # Concatenate text blocks.
                chunks: list[str] = []
                for block in resp.content:
                    txt = getattr(block, "text", None)
                    if txt:
                        chunks.append(txt)
                # Track token usage.
                if resp.usage is not None:
                    logger.info(
                        "llm_tokens",
                        extra={
                            "module": "llm",
                            "input_tokens": getattr(resp.usage, "input_tokens", 0),
                            "output_tokens": getattr(resp.usage, "output_tokens", 0),
                        },
                    )
                return "".join(chunks)

            return await asyncio.to_thread(_call)
        except Exception as exc:
            # Detect rate limit (Anthropic raises RateLimitError; status 429).
            cls = type(exc).__name__
            if "RateLimit" in cls or "rate_limit" in str(exc).lower():
                raise PipelineBusyError("LLM 限流") from exc
            raise LLMProviderError(f"LLM call failed: {exc}") from exc

    async def summarize(self, title: str, source: str, raw_text: str) -> SummaryResult:
        """Convenience: build prompt + parse result."""
        prompt = _build_prompt(title, source, raw_text)
        raw = await self.complete_json(prompt)
        return _parse_summary_response(raw)


__all__ = ["LLMClient", "LLMProviderError", "SummaryResult"]
