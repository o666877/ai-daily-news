"""Unit tests for app/infra/llm.py.

Covers:
- LLMClient init: uses provided args or settings
- LLMClient init: fallback api_key when settings empty
- _parse_summary_response: happy path, malformed JSON, markdown fence stripping
- complete_json: transport failure → LLMProviderError
- summarize: convenience delegates to complete_json
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.infra.llm import (
    LLMClient,
    LLMProviderError,
    SummaryResult,
    _ensure_chinese,
    _is_mostly_chinese,
    _parse_summary_response,
)


# ---------- LLMClient init ----------

def test_llm_client_uses_provided_args():
    """Constructor uses explicit args, not settings."""
    client = LLMClient(
        base_url="https://custom.example.com",
        api_key="explicit-key",
        model="custom-model",
    )
    assert client.base_url == "https://custom.example.com"
    assert client.api_key == "explicit-key"
    assert client.model == "custom-model"


def test_llm_client_falls_back_to_settings(monkeypatch):
    """When args are None, use settings.llm_*."""
    monkeypatch.setenv("AIDAILY_LLM_BASE_URL", "https://settings.example.com")
    monkeypatch.setenv("AIDAILY_LLM_API_KEY", "settings-key")
    monkeypatch.setenv("AIDAILY_LLM_MODEL", "settings-model")
    from app.config import reset_settings_cache
    reset_settings_cache()

    client = LLMClient()
    assert client.base_url == "https://settings.example.com"
    assert client.api_key == "settings-key"
    assert client.model == "settings-model"


def test_llm_client_uses_test_key_when_api_key_empty(monkeypatch):
    """When settings.llm_api_key is empty, use 'test-key' placeholder."""
    monkeypatch.setenv("AIDAILY_LLM_API_KEY", "")
    from app.config import reset_settings_cache
    reset_settings_cache()

    client = LLMClient()
    assert client.api_key == "test-key"


# ---------- _parse_summary_response ----------

def test_parse_summary_happy_path():
    text = json.dumps(
        {
            "title": "中文标题",
            "lede": "导语",
            "summary": "一句话总结",
            "body": "**段1** 正文。\n\n段2 提到 `pip install x`。",
            "quote": "原话",
            "points": ["要点1", "要点2"],
        },
        ensure_ascii=False,
    )
    result = _parse_summary_response(text)
    assert isinstance(result, SummaryResult)
    assert result.title == "中文标题"
    assert result.lede == "导语"
    assert result.summary == "一句话总结"
    assert result.body == "**段1** 正文。\n\n段2 提到 `pip install x`。"
    assert result.quote == "原话"
    assert result.points == ["要点1", "要点2"]


def test_parse_summary_strips_markdown_fence():
    """Markdown code-fenced JSON is unwrapped before parsing."""
    text = '```json\n{"title": "T", "lede": "L", "summary": "S", "body": "P", "quote": null, "points": ["X"]}\n```'
    result = _parse_summary_response(text)
    assert result.title == "T"
    assert result.lede == "L"
    assert result.summary == "S"
    assert result.body == "P"
    assert result.quote is None
    assert result.points == ["X"]


def test_parse_summary_handles_null_quote():
    text = json.dumps(
        {"title": "T", "lede": "L", "summary": "S", "body": "P", "quote": None, "points": ["X"]},
        ensure_ascii=False,
    )
    result = _parse_summary_response(text)
    assert result.quote is None


def test_parse_summary_body_array_tolerated_and_joined():
    """Legacy array body format is joined with blank lines into one md string."""
    text = json.dumps(
        {
            "title": "T",
            "lede": "L",
            "summary": "S",
            "body": ["段1", "", "段3"],
            "quote": None,
            "points": ["要点1", ""],
        },
        ensure_ascii=False,
    )
    result = _parse_summary_response(text)
    # Empty segments dropped, remaining joined with \n\n.
    assert result.body == "段1\n\n段3"
    assert result.points == ["要点1"]


def test_parse_summary_body_null_and_missing_become_empty_string():
    text = json.dumps(
        {"title": "T", "lede": "L", "summary": "S", "body": None, "quote": None, "points": ["X"]},
        ensure_ascii=False,
    )
    assert _parse_summary_response(text).body == ""
    missing = json.dumps({"title": "T", "lede": "L", "summary": "S", "quote": None, "points": []})
    assert _parse_summary_response(missing).body == ""


def test_parse_summary_defaults_missing_fields():
    """Missing fields → empty string/list, NOT raise."""
    text = json.dumps({"lede": "L"}, ensure_ascii=False)
    result = _parse_summary_response(text)
    assert result.lede == "L"
    assert result.title == "L"  # title falls back to truncated lede
    assert result.summary == ""
    assert result.body == ""
    assert result.quote is None
    assert result.points == []


# ---------- _parse_summary_response: scoring + dedup fields (US1 T011) ----------

def test_parse_summary_extracts_dimension_scores():
    """dimensionScores nested object maps to dimension_scores dict."""
    text = json.dumps(
        {
            "title": "中文标题",
            "lede": "导语",
            "summary": "总结",
            "body": ["段"],
            "quote": None,
            "points": ["要点"],
            "dimensionScores": {
                "authority": 90,
                "depth": 80,
                "timeliness": 70,
                "expression": 60,
            },
        },
        ensure_ascii=False,
    )
    result = _parse_summary_response(text)
    assert result.dimension_scores == {
        "authority": 90,
        "depth": 80,
        "timeliness": 70,
        "expression": 60,
    }


def test_parse_summary_extracts_topic_id():
    text = json.dumps(
        {
            "title": "T",
            "lede": "L",
            "summary": "S",
            "body": ["P"],
            "quote": None,
            "points": ["X"],
            "topicId": "gpt5-release",
        },
        ensure_ascii=False,
    )
    result = _parse_summary_response(text)
    assert result.topic_id == "gpt5-release"


def test_parse_summary_extracts_opinion_fingerprint():
    text = json.dumps(
        {
            "title": "T",
            "lede": "L",
            "summary": "S",
            "body": ["P"],
            "quote": None,
            "points": ["X"],
            "opinionFingerprint": "critical-analysis",
        },
        ensure_ascii=False,
    )
    result = _parse_summary_response(text)
    assert result.opinion_fingerprint == "critical-analysis"


def test_parse_summary_scoring_fields_default_to_none_when_absent():
    """Missing dimensionScores / topicId / opinionFingerprint → None (tolerate)."""
    text = json.dumps(
        {
            "title": "T",
            "lede": "L",
            "summary": "S",
            "body": ["P"],
            "quote": None,
            "points": ["X"],
        },
        ensure_ascii=False,
    )
    result = _parse_summary_response(text)
    assert result.dimension_scores is None
    assert result.topic_id is None
    assert result.opinion_fingerprint is None


def test_parse_summary_topic_id_null_tolerated():
    """Explicit null topicId → None (not error)."""
    text = json.dumps(
        {
            "title": "T",
            "lede": "L",
            "summary": "S",
            "body": ["P"],
            "quote": None,
            "points": ["X"],
            "topicId": None,
            "opinionFingerprint": None,
        },
        ensure_ascii=False,
    )
    result = _parse_summary_response(text)
    assert result.topic_id is None
    assert result.opinion_fingerprint is None


def test_parse_summary_dimension_scores_partial_dict_tolerated():
    """If LLM only emits some dimension keys, only those are kept."""
    text = json.dumps(
        {
            "title": "T",
            "lede": "L",
            "summary": "S",
            "body": ["P"],
            "quote": None,
            "points": ["X"],
            "dimensionScores": {"authority": 80, "depth": 70},
        },
        ensure_ascii=False,
    )
    result = _parse_summary_response(text)
    # Partial: only authority + depth present
    assert result.dimension_scores == {"authority": 80, "depth": 70}


def test_parse_summary_raises_on_invalid_json():
    """Non-JSON text → LLMProviderError."""
    with pytest.raises(LLMProviderError) as exc_info:
        _parse_summary_response("not a json at all")
    assert "non-JSON" in str(exc_info.value)


# ---------- complete_json ----------

@pytest.mark.asyncio
async def test_complete_json_success():
    """Happy path: underlying Anthropic client returns text."""
    fake_response = MagicMock()
    fake_response.content = [MagicMock(text=json.dumps(
        {"title": "T", "lede": "L", "summary": "S", "body": ["P"], "quote": None, "points": ["X"]}
    ))]

    fake_anthropic = MagicMock()
    fake_anthropic.messages.create.return_value = fake_response

    with patch("app.infra.llm.anthropic") as mod:
        mod.Anthropic.return_value = fake_anthropic
        client = LLMClient(
            base_url="https://api.example.com",
            api_key="key",
            model="model",
        )
        # Force client rebuild
        client._client = fake_anthropic
        text = await client.complete_json("prompt")
    assert "lede" in text or "L" in text


@pytest.mark.asyncio
async def test_complete_json_transport_failure_raises_provider_error():
    """Generic Exception → LLMProviderError."""
    fake_anthropic = MagicMock()
    fake_anthropic.messages.create.side_effect = RuntimeError("connection reset")

    client = LLMClient()
    client._client = fake_anthropic

    with pytest.raises(LLMProviderError):
        await client.complete_json("prompt")


@pytest.mark.asyncio
async def test_complete_json_rate_limit_raises_retryable_error():
    """Anthropic RateLimitError → LLMRateLimitError (retryable, subclass of
    LLMProviderError so tenacity picks it up; not PipelineBusyError which is
    reserved for budget exhaustion)."""
    fake_anthropic = MagicMock()

    # Build a fake RateLimitError class
    class FakeRateLimitError(Exception):
        pass

    fake_anthropic.messages.create.side_effect = FakeRateLimitError("rate limit")

    client = LLMClient()
    client._client = fake_anthropic

    with pytest.raises(LLMProviderError):
        await client.complete_json("prompt")


@pytest.mark.asyncio
async def test_complete_json_no_client_raises():
    """If anthropic SDK is None or _client is None → LLMProviderError."""
    client = LLMClient()
    client._client = None
    with pytest.raises(LLMProviderError):
        await client.complete_json("prompt")


# ---------- summarize ----------

@pytest.mark.asyncio
async def test_summarize_delegates_to_complete_json():
    """summarize() wraps complete_json() with prompt building.

    Note: fixture fields are Chinese to avoid firing _ensure_chinese retry.
    """
    client = LLMClient()

    # Patch complete_json to assert it's called
    called = {"n": 0, "prompt": None}

    async def fake_complete(prompt, system=None, *, max_tokens=1200):
        called["n"] += 1
        called["prompt"] = prompt
        return json.dumps(
            {
                "title": "中文标题",
                "lede": "中文导语段落",
                "summary": "中文一句话总结",
                "body": ["中文段落一"],
                "quote": "中文引用",
                "points": ["中文要点一"],
            },
            ensure_ascii=False,
        )

    client.complete_json = fake_complete  # type: ignore[method-assign]
    result = await client.summarize(title="原标题", source="source-x", raw_text="raw content")
    # Single call: primary summarization only (all-Chinese → no translation retry).
    assert called["n"] == 1
    assert "原标题" in called["prompt"]
    assert result.title == "中文标题"
    assert result.lede == "中文导语段落"
    assert result.quote == "中文引用"


# ---------- _is_mostly_chinese ----------

def test_is_mostly_chinese_pure_english_is_false():
    assert _is_mostly_chinese("We are releasing GPT-5 today") is False


def test_is_mostly_chinese_pure_chinese_is_true():
    assert _is_mostly_chinese("今天发布了新产品") is True


def test_is_mostly_chinese_mixed_above_threshold_is_true():
    # 4 hanzi, ~7 ascii letters → ratio 4/11 ≈ 0.36 >= 0.30 → True
    assert _is_mostly_chinese("OpenAI 发布了新模型") is True


def test_is_mostly_chinese_mixed_below_threshold_is_false():
    # 1 hanzi, 14 ascii letters → ratio 1/15 ≈ 0.067 < 0.30 → False
    assert _is_mostly_chinese("The model name is GPT amazing") is False


def test_is_mostly_chinese_empty_is_true():
    assert _is_mostly_chinese("") is True
    assert _is_mostly_chinese(None) is True


def test_is_mostly_chinese_pure_punctuation_is_true():
    # No linguistic content; treated as vacuously OK.
    assert _is_mostly_chinese("--- ... ---") is True


def test_is_mostly_chinese_mixed_with_long_english_run_is_false():
    # Regression: LLM kept English original as parenthetical alongside
    # Chinese translation. Overall ratio passes (0.38) but contains
    # "workbench" (9 chars) → must fail stage 2.
    quote = "该项目被定位为 'A workbench for language model research'（一个用于语言模型研究的工作台）。"
    assert _is_mostly_chinese(quote) is False


def test_is_mostly_chinese_short_proper_nouns_pass():
    # Proper nouns up to 8 chars (OpenAI=6, Claude=6, PyTorch=7, GitHub=6)
    # must not trip stage-2 false positive when embedded in Chinese-heavy text.
    s = "今天 OpenAI 发布了 Claude 新版本，PyTorch 框架也同步升级支持新特性"
    assert _is_mostly_chinese(s) is True


# ---------- _ensure_chinese ----------

@pytest.mark.asyncio
async def test_ensure_chinese_translates_english_quote():
    """English quote field is re-translated; other fields unchanged."""
    result = SummaryResult(
        title="中文标题",
        lede="中文导语",
        summary="中文摘要",
        body="中文段落",
        quote="This is an English quote that should be translated",
        points=["中文要点1", "中文要点2"],
    )

    class _StubClient:
        def __init__(self):
            self.calls: list[str] = []

        async def complete_json(self, prompt, system=None, *, max_tokens=1200):
            self.calls.append(prompt)
            return "这是被翻译的中文引用"

    stub = _StubClient()
    out = await _ensure_chinese(result, stub, original_text="raw")

    # Translation invoked exactly once (only quote field was non-Chinese).
    assert len(stub.calls) == 1
    assert _is_mostly_chinese(out.quote) is True
    assert out.title == "中文标题"
    assert out.lede == "中文导语"
    assert out.summary == "中文摘要"
    assert out.points == ["中文要点1", "中文要点2"]


@pytest.mark.asyncio
async def test_ensure_chinese_translates_all_english_fields():
    """Multiple non-Chinese fields each get their own translation call."""
    result = SummaryResult(
        title="Some English Title",
        lede="English lede paragraph",
        summary="English summary",
        body="x",
        quote="English quote",
        points=["point one", "point two"],
    )

    class _CountingClient:
        def __init__(self):
            self.n = 0

        async def complete_json(self, prompt, system=None, *, max_tokens=1200):
            self.n += 1
            return f"中文翻译{self.n}"

    stub = _CountingClient()
    out = await _ensure_chinese(result, stub, original_text="raw")

    # 5 fields (title, lede, summary, quote, 2 points) = 6 calls
    assert stub.n == 6
    assert _is_mostly_chinese(out.title)
    assert _is_mostly_chinese(out.lede)
    assert _is_mostly_chinese(out.summary)
    assert _is_mostly_chinese(out.quote)
    assert all(_is_mostly_chinese(p) for p in out.points)


@pytest.mark.asyncio
async def test_ensure_chinese_translation_failure_returns_original():
    """If translation call raises, the field is kept unchanged."""
    result = SummaryResult(
        title="中文标题",
        lede="中文导语",
        summary="中文摘要",
        body="x",
        quote="English quote that failed to translate",
        points=["中文要点"],
    )

    class _FailingClient:
        async def complete_json(self, prompt, system=None, *, max_tokens=1200):
            raise LLMProviderError("translation service down")

    stub = _FailingClient()
    out = await _ensure_chinese(result, stub, original_text="raw")

    # Fallback: original quote preserved, no exception propagated.
    assert out.quote == "English quote that failed to translate"
    assert out.title == "中文标题"


@pytest.mark.asyncio
async def test_ensure_chinese_skips_already_chinese():
    """No translation calls fire if everything is already Chinese."""
    result = SummaryResult(
        title="中文标题",
        lede="中文导语",
        summary="中文摘要",
        body="x",
        quote="中文引用",
        points=["要点一"],
    )

    class _BombClient:
        async def complete_json(self, prompt, system=None, *, max_tokens=1200):
            raise AssertionError("should not be called")

    out = await _ensure_chinese(result, _BombClient(), original_text="raw")
    assert out == result


@pytest.mark.asyncio
async def test_ensure_chinese_skips_numeric_dimension_scores():
    """dimension_scores (dict) is never sent to translation — numeric data."""
    result = SummaryResult(
        title="中文标题",
        lede="中文导语",
        summary="中文摘要",
        body="x",
        quote="中文引用",
        points=["要点"],
        dimension_scores={"authority": 90, "depth": 80},
        topic_id="gpt5-release",
        opinion_fingerprint="official-announcement",
    )

    class _CountingClient:
        def __init__(self):
            self.n = 0

        async def complete_json(self, prompt, system=None, *, max_tokens=1200):
            self.n += 1
            return "translated"

    stub = _CountingClient()
    out = await _ensure_chinese(result, stub, original_text="raw")
    # No translation calls (dimension_scores is dict, str id fields are
    # allowed to remain in original form per D4: "topics are identifiers")
    assert stub.n == 0
    # dimension_scores preserved exactly
    assert out.dimension_scores == {"authority": 90, "depth": 80}
    assert out.topic_id == "gpt5-release"
    assert out.opinion_fingerprint == "official-announcement"


__all__ = []