"""Spec 006 / Ticket 01: im_push 纯函数校验 — 掩码、占位符回填、默认值."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.settings import (
    ImPush,
    default_im_push,
    is_masked_webhook_url,
    mask_webhook_url,
    resolve_im_push,
)

FULL_URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abcd1234efgh5678"


class TestMaskWebhookUrl:
    def test_masks_key_to_last_four(self) -> None:
        assert mask_webhook_url(FULL_URL) == (
            "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=****5678"
        )

    def test_short_key_keeps_whole_mask(self) -> None:
        url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abcdefgh"
        assert mask_webhook_url(url) == (
            "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=****efgh"
        )

    def test_is_masked_detection(self) -> None:
        assert is_masked_webhook_url(
            "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=****5678"
        )
        assert not is_masked_webhook_url(FULL_URL)


class TestImPushValidation:
    def test_defaults(self) -> None:
        im = ImPush()
        assert im.enabled is False
        assert im.top_n == 5
        assert im.link_base_url == ""
        assert im.webhooks == []

    def test_valid_full_url_accepted(self) -> None:
        im = ImPush(webhooks=[{"name": "main", "url": FULL_URL}])
        assert im.webhooks[0].url == FULL_URL

    def test_masked_url_accepted_as_placeholder(self) -> None:
        im = ImPush(webhooks=[{"name": "main", "url": mask_webhook_url(FULL_URL)}])
        assert is_masked_webhook_url(im.webhooks[0].url)

    @pytest.mark.parametrize(
        "url",
        [
            "https://evil.example.com/cgi-bin/webhook/send?key=abcd1234efgh5678",
            "http://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abcd1234efgh5678",
            "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=short",
            "not-a-url",
        ],
    )
    def test_invalid_url_rejected(self, url: str) -> None:
        with pytest.raises(ValidationError):
            ImPush(webhooks=[{"name": "main", "url": url}])

    def test_six_webhooks_rejected(self) -> None:
        hooks = [
            {"name": f"g{i}", "url": FULL_URL} for i in range(6)
        ]
        with pytest.raises(ValidationError):
            ImPush(webhooks=hooks)

    @pytest.mark.parametrize("name", ["", "x" * 21])
    def test_name_length_rejected(self, name: str) -> None:
        with pytest.raises(ValidationError):
            ImPush(webhooks=[{"name": name, "url": FULL_URL}])

    @pytest.mark.parametrize("top_n", [2, 11, 0])
    def test_top_n_out_of_range(self, top_n: int) -> None:
        with pytest.raises(ValidationError):
            ImPush(top_n=top_n)

    @pytest.mark.parametrize("base", ["notaurl", "ftp://x", "https://"])
    def test_link_base_url_invalid(self, base: str) -> None:
        with pytest.raises(ValidationError):
            ImPush(link_base_url=base)

    def test_link_base_url_valid(self) -> None:
        assert ImPush(link_base_url="https://daily.example.com").link_base_url == (
            "https://daily.example.com"
        )


class TestResolveImPush:
    def test_full_urls_pass_through(self) -> None:
        submitted = ImPush(enabled=True, webhooks=[{"name": "main", "url": FULL_URL}])
        resolved = resolve_im_push(submitted, None)
        assert resolved["webhooks"][0]["url"] == FULL_URL
        assert resolved["enabled"] is True

    def test_placeholder_restores_original(self) -> None:
        existing = {"webhooks": [{"name": "main", "url": FULL_URL}]}
        submitted = ImPush(
            webhooks=[{"name": "main", "url": mask_webhook_url(FULL_URL)}]
        )
        resolved = resolve_im_push(submitted, existing)
        assert resolved["webhooks"][0]["url"] == FULL_URL

    def test_placeholder_without_match_rejected(self) -> None:
        submitted = ImPush(
            webhooks=[
                {
                    "name": "main",
                    "url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=****9999",
                }
            ]
        )
        with pytest.raises(ValueError, match="9999"):
            resolve_im_push(submitted, None)

    def test_placeholder_ambiguous_match_rejected(self) -> None:
        # 两个已存 webhook 尾 4 位相同:占位符无法唯一回填,要求重交完整地址
        other = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=zzzz9999wxyz5678"
        existing = {"webhooks": [{"name": "a", "url": FULL_URL}, {"name": "b", "url": other}]}
        submitted = ImPush(
            webhooks=[{"name": "a", "url": mask_webhook_url(FULL_URL)}]
        )
        with pytest.raises(ValueError, match="唯一"):
            resolve_im_push(submitted, existing)

    def test_none_returns_existing_raw(self) -> None:
        existing = {"enabled": True}
        assert resolve_im_push(None, existing) == existing

    def test_none_returns_deep_copy(self) -> None:
        existing = {"webhooks": [{"name": "a", "url": FULL_URL}]}
        resolved = resolve_im_push(None, existing)
        resolved["webhooks"][0]["url"] = "mutated"
        assert existing["webhooks"][0]["url"] == FULL_URL


class TestDefaults:
    def test_default_im_push_dict(self) -> None:
        d = default_im_push()
        assert d == {
            "enabled": False,
            "top_n": 5,
            "link_base_url": "",
            "webhooks": [],
        }
        ImPush.model_validate(d)  # canonical shape stays valid

    def test_empty_raw_maps_to_defaults(self) -> None:
        assert ImPush.model_validate({}).enabled is False
        assert ImPush.model_validate(None or {}).webhooks == []
