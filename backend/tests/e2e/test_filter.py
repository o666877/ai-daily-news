"""T053: Browser contract for dual-dimension article filtering."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect


@pytest.mark.e2e
def test_type_and_source_filters(page: Page, base_url: str):
    page.goto(base_url + "/")
    type_group = page.locator(".badge-group").nth(0)
    source_group = page.locator(".badge-group").nth(1)
    type_group.locator(".badge", has_text="Agent").first.click()
    expect(page.locator(".article-item").first).to_contain_text("Agent")
    source_group.locator(".badge", has_text="Reddit").first.click()
    articles = page.locator(".article-item")
    expect(articles).to_have_count(1)
    expect(articles.first).to_contain_text("Reddit")

    # Switch type to Tools, keep Reddit source -> no match -> empty state.
    type_group.locator(".badge", has_text="工具效率").first.click()
    expect(page.get_by_text("今天的货架是空的")).to_be_visible()
