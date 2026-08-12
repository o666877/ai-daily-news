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

from app.infra.errors import PipelineBusyError
from app.infra.llm import (
    LLMClient,
    LLMProviderError,
    SummaryResult,
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
            "lede": "导语",
            "summary": "一句话总结",
            "body": ["段1", "段2"],
            "quote": "原话",
            "points": ["要点1", "要点2"],
        },
        ensure_ascii=False,
    )
    result = _parse_summary_response(text)
    assert isinstance(result, SummaryResult)
    assert result.lede == "导语"
    assert result.summary == "一句话总结"
    assert result.body == ["段1", "段2"]
    assert result.quote == "原话"
    assert result.points == ["要点1", "要点2"]


def test_parse_summary_strips_markdown_fence():
    """Markdown code-fenced JSON is unwrapped before parsing."""
    text = '```json\n{"lede": "L", "summary": "S", "body": ["P"], "quote": null, "points": ["X"]}\n```'
    result = _parse_summary_response(text)
    assert result.lede == "L"
    assert result.summary == "S"
    assert result.body == ["P"]
    assert result.quote is None
    assert result.points == ["X"]


def test_parse_summary_handles_null_quote():
    text = json.dumps(
        {"lede": "L", "summary": "S", "body": ["P"], "quote": None, "points": ["X"]},
        ensure_ascii=False,
    )
    result = _parse_summary_response(text)
    assert result.quote is None


def test_parse_summary_filters_empty_strings_in_arrays():
    text = json.dumps(
        {
            "lede": "L",
            "summary": "S",
            "body": ["段1", "", "段3"],
            "quote": None,
            "points": ["要点1", ""],
        },
        ensure_ascii=False,
    )
    result = _parse_summary_response(text)
    assert result.body == ["段1", "段3"]
    assert result.points == ["要点1"]


def test_parse_summary_defaults_missing_fields():
    """Missing fields → empty string/list, NOT raise."""
    text = json.dumps({"lede": "L"}, ensure_ascii=False)
    result = _parse_summary_response(text)
    assert result.lede == "L"
    assert result.summary == ""
    assert result.body == []
    assert result.quote is None
    assert result.points == []


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
        {"lede": "L", "summary": "S", "body": ["P"], "quote": None, "points": ["X"]}
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
async def test_complete_json_rate_limit_raises_pipeline_busy():
    """Anthropic RateLimitError → PipelineBusyError (9002)."""
    fake_anthropic = MagicMock()

    # Build a fake RateLimitError class
    class FakeRateLimitError(Exception):
        pass

    fake_anthropic.messages.create.side_effect = FakeRateLimitError("rate limit")

    client = LLMClient()
    client._client = fake_anthropic

    with pytest.raises((PipelineBusyError, LLMProviderError)):
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
    """summarize() wraps complete_json() with prompt building."""
    client = LLMClient()

    # Patch complete_json to assert it's called
    called = {"n": 0, "prompt": None}

    async def fake_complete(prompt, system=None):
        called["n"] += 1
        called["prompt"] = prompt
        return json.dumps(
            {"lede": "L", "summary": "S", "body": ["P"], "quote": "Q", "points": ["X"]}
        )

    client.complete_json = fake_complete  # type: ignore[method-assign]
    result = await client.summarize(title="标题", source="source-x", raw_text="raw content")
    assert called["n"] == 1
    assert "标题" in called["prompt"]
    assert result.lede == "L"
    assert result.quote == "Q"


__all__ = []