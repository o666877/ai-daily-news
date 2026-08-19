"""Unit tests for individual collectors (github, reddit, web, x_rsshub).

Each collector is exercised in isolation with monkeypatched settings +
httpx-mocked or fallback behavior. Network is never touched.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.config import reset_settings_cache
from app.models.article import RawItem
from app.models.meta import SourceKey


# ---------- helpers ----------

def _patch_settings(monkeypatch, **overrides):
    defaults = {
        "AIDAILY_GITHUB_TOKEN": "",
        "AIDAILY_X_RSSHUB_BASE_URL": "",
        "AIDAILY_X_ACCOUNTS": "",
        "AIDAILY_REDDIT_UA": "ai-daily/test",
    }
    for k, v in overrides.items():
        monkeypatch.setenv(k, v)
    reset_settings_cache()


# ---------- GitHub collector (gh CLI) ----------

def _fake_subprocess(json_payload: list[dict], returncode: int = 0, stderr: str = ""):
    """Build a MagicMock async context simulating asyncio.create_subprocess_exec.

    Communicates stdout/stderr as bytes; `returncode` set on the proc object.
    """
    import json as _json

    stdout_b = _json.dumps(json_payload).encode("utf-8")
    stderr_b = stderr.encode("utf-8")

    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout_b, stderr_b))
    proc.kill = MagicMock()
    proc.wait = AsyncMock(return_value=0)

    create_call = MagicMock(return_value=proc)
    return create_call, proc


@pytest.mark.asyncio
async def test_collect_github_no_gh_binary_returns_empty(monkeypatch):
    """When `gh` is not on PATH, return [] and skip everything."""
    _patch_settings(monkeypatch)

    from app.pipeline.collectors import github as gh_module

    monkeypatch.setattr(gh_module.shutil, "which", lambda _: None)

    # If this were called, the test would error — make sure it isn't.
    sentinel = MagicMock(side_effect=AssertionError("should not spawn subprocess"))
    monkeypatch.setattr(gh_module.asyncio, "create_subprocess_exec", sentinel)

    items = await gh_module.collect_github()
    assert items == []


@pytest.mark.asyncio
async def test_collect_github_happy_path(monkeypatch):
    """One successful query with 3 repos -> 3 RawItems with correct fields."""
    _patch_settings(monkeypatch)

    from app.pipeline.collectors import github as gh_module

    payload = [
        {
            "fullName": "user/agent-foo",
            "description": "An agent framework for autonomous workflows",
            "url": "https://github.com/user/agent-foo",
            "stargazersCount": 500,
            "createdAt": "2026-08-10T00:00:00Z",
            "updatedAt": "2026-08-11T00:00:00Z",
            "language": "Python",
        },
        {
            "fullName": "user/llm-bar",
            "description": "A library for LLM fine-tuning",
            "url": "https://github.com/user/llm-bar",
            "stargazersCount": 250,
            "createdAt": "2026-08-09T00:00:00Z",
            "updatedAt": "2026-08-11T00:00:00Z",
            "language": "Python",
        },
        {
            "fullName": "user/tool-baz",
            "description": "Tools for AI agents",
            "url": "https://github.com/user/tool-baz",
            "stargazersCount": 42,
            "createdAt": "2026-08-08T00:00:00Z",
            "updatedAt": "2026-08-12T00:00:00Z",
            "language": "Rust",
        },
    ]

    calls: list[list[str]] = []

    async def fake_create_subprocess_exec(*argv, **_kwargs):
        calls.append(list(argv))
        create_call, _proc = _fake_subprocess(payload, returncode=0)
        return create_call.return_value

    monkeypatch.setattr(gh_module.shutil, "which", lambda _: "/usr/bin/gh")
    monkeypatch.setattr(
        gh_module.asyncio, "create_subprocess_exec", fake_create_subprocess_exec
    )

    items = await gh_module.collect_github()

    assert len(items) == 3
    assert all(i.sourceKey == SourceKey.GITHUB for i in items)
    assert all(i.sourceName == "github.com" for i in items)
    titles = {i.title for i in items}
    assert "user/agent-foo: An agent framework for autonomous workflows" in titles
    # Extra metadata carries stars/language.
    by_url = {i.sourceUrl: i for i in items}
    foo = by_url["https://github.com/user/agent-foo"]
    assert foo.extra["stars"] == 500
    assert foo.extra["language"] == "Python"
    assert foo.publishedAt == "2026-08-10T00:00:00Z"
    # At least one gh call happened.
    assert calls, "expected at least one gh subprocess call"


@pytest.mark.asyncio
async def test_collect_github_aggregates_and_dedups(monkeypatch):
    """Multiple queries aggregate; duplicate URLs are deduped to one item."""
    _patch_settings(monkeypatch)

    from app.pipeline.collectors import github as gh_module

    shared_repo = {
        "fullName": "user/dup",
        "description": "appears in multiple queries",
        "url": "https://github.com/user/dup",
        "stargazersCount": 100,
        "createdAt": "2026-08-08T00:00:00Z",
        "updatedAt": "2026-08-11T00:00:00Z",
        "language": "Python",
    }
    # Query 0 and Query 1 both return the same `shared_repo`; Query 2 adds a unique repo.
    payloads = [
        [shared_repo],  # Q0
        [shared_repo],  # Q1 (dup)
        [
            {
                "fullName": "user/unique",
                "description": "only in Q2",
                "url": "https://github.com/user/unique",
                "stargazersCount": 50,
                "createdAt": "2026-08-09T00:00:00Z",
                "updatedAt": "2026-08-12T00:00:00Z",
                "language": "Go",
            }
        ],  # Q2
    ]
    call_idx = {"i": 0}

    async def fake_create_subprocess_exec(*argv, **_kwargs):
        idx = min(call_idx["i"], len(payloads) - 1)
        call_idx["i"] += 1
        create_call, _proc = _fake_subprocess(payloads[idx], returncode=0)
        return create_call.return_value

    monkeypatch.setattr(gh_module.shutil, "which", lambda _: "/usr/bin/gh")
    monkeypatch.setattr(
        gh_module.asyncio, "create_subprocess_exec", fake_create_subprocess_exec
    )

    items = await gh_module.collect_github()

    urls = sorted(i.sourceUrl for i in items)
    assert urls == [
        "https://github.com/user/dup",
        "https://github.com/user/unique",
    ]


@pytest.mark.asyncio
async def test_collect_github_one_query_fails_others_succeed(monkeypatch):
    """A failing query (non-zero exit) is skipped; successful queries still return data."""
    _patch_settings(monkeypatch)

    from app.pipeline.collectors import github as gh_module

    # Q0 fails (returncode=1), Q1 and Q2 return distinct repos.
    call_idx = {"i": 0}
    good_payload = [
        {
            "fullName": "user/ok-1",
            "description": "first good",
            "url": "https://github.com/user/ok-1",
            "stargazersCount": 10,
            "createdAt": "2026-08-08T00:00:00Z",
            "updatedAt": "2026-08-11T00:00:00Z",
            "language": "Python",
        }
    ]

    async def fake_create_subprocess_exec(*argv, **_kwargs):
        idx = call_idx["i"]
        call_idx["i"] += 1
        if idx == 0:
            # Failure: returncode 1, stderr message, empty stdout.
            create_call, _proc = _fake_subprocess([], returncode=1, stderr="rate limited")
            return create_call.return_value
        create_call, _proc = _fake_subprocess(good_payload, returncode=0)
        return create_call.return_value

    monkeypatch.setattr(gh_module.shutil, "which", lambda _: "/usr/bin/gh")
    monkeypatch.setattr(
        gh_module.asyncio, "create_subprocess_exec", fake_create_subprocess_exec
    )

    items = await gh_module.collect_github()

    # Q1 and Q2 both returned good_payload with one repo; dedup collapses to 1.
    assert len(items) == 1
    assert items[0].sourceUrl == "https://github.com/user/ok-1"


def test_github_build_queries_shape():
    """Query set locks the 5 topics: llm / ai-agents / artificial-intelligence /
    continual-learning / agent-skills — all gh search repos, star-sorted, JSON."""
    from app.pipeline.collectors.github import _build_queries

    queries = _build_queries()
    assert len(queries) == 5
    topics = []
    for q in queries:
        assert q[:3] == ["gh", "search", "repos"]
        assert "--json" in q and "--sort" in q and "--order" in q
        topics.append(q[q.index("--topic") + 1])
    assert topics == [
        "llm", "ai-agents", "artificial-intelligence",
        "continual-learning", "agent-skills",
    ]


# ---------- Reddit collector (Atom .rss feed) ----------
#
# Production uses httpx.AsyncClient + a custom User-Agent and parses the
# returned Atom feed with feedparser. We mock the HTTP transport with respx
# (same approach as the web collector tests above) and feed real-ish Atom
# XML so feedparser exercises the same path as live traffic.


def _atom_entry(
    *,
    title: str,
    permalink: str,
    post_id: str,
    age_hours: float,
    body_html: str = "",
    author: str = "/u/tester",
) -> str:
    """Render one Atom <entry> string for a Reddit top.rss feed.

    `age_hours` controls the published/updated timestamps relative to now
    so tests can exercise the 72h freshness filter without freezing time.
    """
    from datetime import timedelta

    published_dt = datetime.now(tz=timezone.utc) - timedelta(hours=age_hours)
    published_str = published_dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")

    # Reddit's feed embeds post id in the entry <id> path too.
    entry_id = permalink  # permalink is already absolute; feedparser is fine with it.

    content_xml = ""
    if body_html:
        # Escape only the XML-significant chars; body is HTML wrapped in CDATA.
        content_xml = f'<content type="html"><![CDATA[{body_html}]]></content>'

    return (
        "<entry>"
        f"<title>{title}</title>"
        f'<link rel="alternate" href="{permalink}" type="text/html" />'
        f"<id>{entry_id}</id>"
        f"<published>{published_str}</published>"
        f"<updated>{published_str}</updated>"
        f"<author><name>{author}</name></author>"
        f"{content_xml}"
        "</entry>"
    )


def _atom_feed(entries_xml: list[str]) -> str:
    """Wrap entry strings in a minimal Atom <feed> document."""
    body = "".join(entries_xml)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom">'
        "<title>top scoring links</title>"
        f"{body}"
        "</feed>"
    )


@pytest.mark.asyncio
async def test_collect_reddit_happy_path(monkeypatch):
    """One sub returns 3 fresh posts → 3 RawItems; other subs return empty."""
    _patch_settings(monkeypatch)

    from app.pipeline.collectors import reddit as reddit_mod

    monkeypatch.setattr(reddit_mod, "SUBREDDITS", ["MachineLearning", "EmptySub"])

    three_entries = [
        _atom_entry(
            title="New transformer architecture",
            permalink="https://www.reddit.com/r/MachineLearning/comments/abc1/new_transformer/",
            post_id="abc1",
            age_hours=1,
            body_html="",  # no body → rawText falls back to title
        ),
        _atom_entry(
            title="Self-post about agents",
            permalink="https://www.reddit.com/r/MachineLearning/comments/def2/self_post_about_agents/",
            post_id="def2",
            age_hours=2,
            body_html="<div><p>discussion of agent frameworks</p></div>",
        ),
        _atom_entry(
            title="Open source release",
            permalink="https://www.reddit.com/r/MachineLearning/comments/ghi3/open_source_release/",
            post_id="ghi3",
            age_hours=3,
        ),
    ]

    import respx
    with respx.mock(assert_all_called=False) as router:
        router.get(
            "https://www.reddit.com/r/MachineLearning/top/.rss"
        ).respond(status_code=200, text=_atom_feed(three_entries))
        router.get("https://www.reddit.com/r/EmptySub/top/.rss").respond(
            status_code=200, text=_atom_feed([])
        )
        items = await reddit_mod.collect_reddit()

    assert len(items) == 3
    assert all(it.sourceKey == SourceKey.REDDIT for it in items)
    assert all(it.extra["subreddit"] == "MachineLearning" for it in items)

    # Permalink preserved verbatim; post_id extracted from the comments path.
    assert items[0].title == "New transformer architecture"
    assert items[0].sourceUrl == (
        "https://www.reddit.com/r/MachineLearning/comments/abc1/new_transformer/"
    )
    assert items[0].extra["post_id"] == "abc1"
    # publishedAt is an ISO string built from the feed timestamp.
    assert items[0].publishedAt.startswith("20")

    # HTML body stripped and folded into rawText for the second post.
    assert "discussion of agent frameworks" in items[1].rawText
    # No body → rawText falls back to title only.
    assert items[0].rawText == "New transformer architecture"


@pytest.mark.asyncio
async def test_collect_reddit_stale_posts_filtered(monkeypatch):
    """Posts older than FRESH_WINDOW_HOURS are dropped."""
    _patch_settings(monkeypatch)

    from app.pipeline.collectors import reddit as reddit_mod

    monkeypatch.setattr(reddit_mod, "SUBREDDITS", ["TestSub"])

    entries = [
        _atom_entry(
            title="Fresh post",
            permalink="https://www.reddit.com/r/TestSub/comments/fresh/fresh_post/",
            post_id="fresh",
            age_hours=1,
        ),
        _atom_entry(
            title="Stale post",
            permalink="https://www.reddit.com/r/TestSub/comments/stale/stale_post/",
            post_id="stale",
            age_hours=100,  # beyond 72h window
        ),
    ]

    import respx
    with respx.mock(assert_all_called=False) as router:
        router.get("https://www.reddit.com/r/TestSub/top/.rss").respond(
            status_code=200, text=_atom_feed(entries)
        )
        items = await reddit_mod.collect_reddit()

    assert len(items) == 1
    assert items[0].title == "Fresh post"


@pytest.mark.asyncio
async def test_collect_reddit_one_sub_404_others_continue(monkeypatch):
    """Sub A 404s → skipped; Sub B still returns posts (FR-007a)."""
    _patch_settings(monkeypatch)

    from app.pipeline.collectors import reddit as reddit_mod

    monkeypatch.setattr(reddit_mod, "SUBREDDITS", ["BadSub", "GoodSub"])

    good_entries = [
        _atom_entry(
            title="Working post",
            permalink="https://www.reddit.com/r/GoodSub/comments/wp1/working_post/",
            post_id="wp1",
            age_hours=1,
        )
    ]

    import respx
    with respx.mock(assert_all_called=False) as router:
        router.get("https://www.reddit.com/r/BadSub/top/.rss").respond(status_code=404)
        router.get("https://www.reddit.com/r/GoodSub/top/.rss").respond(
            status_code=200, text=_atom_feed(good_entries)
        )
        items = await reddit_mod.collect_reddit()

    assert len(items) == 1
    assert items[0].title == "Working post"
    assert items[0].extra["subreddit"] == "GoodSub"


@pytest.mark.asyncio
async def test_collect_reddit_malformed_xml_skipped(monkeypatch):
    """Sub returns 200 but unparseable XML → skipped; others continue."""
    _patch_settings(monkeypatch)

    from app.pipeline.collectors import reddit as reddit_mod

    monkeypatch.setattr(reddit_mod, "SUBREDDITS", ["BrokenSub", "GoodSub"])

    good_entries = [
        _atom_entry(
            title="Ok post",
            permalink="https://www.reddit.com/r/GoodSub/comments/ok1/ok_post/",
            post_id="ok1",
            age_hours=1,
        )
    ]

    import respx
    with respx.mock(assert_all_called=False) as router:
        router.get("https://www.reddit.com/r/BrokenSub/top/.rss").respond(
            status_code=200, text="<<not xml>> garbage"
        )
        router.get("https://www.reddit.com/r/GoodSub/top/.rss").respond(
            status_code=200, text=_atom_feed(good_entries)
        )
        items = await reddit_mod.collect_reddit()

    assert len(items) == 1
    assert items[0].title == "Ok post"


@pytest.mark.asyncio
async def test_collect_reddit_uses_configured_user_agent(monkeypatch):
    """AIDAILY_REDDIT_UA overrides the default and is sent on each request."""
    _patch_settings(monkeypatch, AIDAILY_REDDIT_UA="my-test-bot/2.0 (by u/tester)")

    from app.pipeline.collectors import reddit as reddit_mod

    monkeypatch.setattr(reddit_mod, "SUBREDDITS", ["AgentAI"])

    captured_headers: dict[str, str] = {}

    import respx
    with respx.mock(assert_all_called=False) as router:

        def _handler(request):
            captured_headers.update(dict(request.headers))
            from httpx import Response
            return Response(200, text=_atom_feed([]))

        router.get("https://www.reddit.com/r/AgentAI/top/.rss").mock(side_effect=_handler)
        await reddit_mod.collect_reddit()

    assert captured_headers.get("user-agent") == "my-test-bot/2.0 (by u/tester)"


@pytest.mark.asyncio
async def test_collect_reddit_all_subs_fail_returns_empty(monkeypatch):
    """Every sub returns 500 → empty list, no raise."""
    _patch_settings(monkeypatch)

    from app.pipeline.collectors import reddit as reddit_mod

    monkeypatch.setattr(reddit_mod, "SUBREDDITS", ["DownA", "DownB"])

    import respx
    with respx.mock(assert_all_called=False) as router:
        router.get("https://www.reddit.com/r/DownA/top/.rss").respond(status_code=500)
        router.get("https://www.reddit.com/r/DownB/top/.rss").respond(status_code=500)
        items = await reddit_mod.collect_reddit()

    assert items == []


# ---------- Web (RSS/Atom feedparser) collector ----------
#
# We mock at the HTTP transport layer with respx because production uses
# httpx.AsyncClient to fetch feeds.

_SAMPLE_RSS_3: str = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example AI Blog</title>
    <link>https://blog.example.com/</link>
    <description>Sample</description>
    <item>
      <title>Agent framework released</title>
      <link>https://blog.example.com/post-1</link>
      <description>Body of the first article.</description>
      <pubDate>Wed, 13 Aug 2026 02:00:00 GMT</pubDate>
    </item>
    <item>
      <title>New open-source LLM</title>
      <link>https://blog.example.com/post-2</link>
      <description>Body of the second article.</description>
      <pubDate>Wed, 13 Aug 2026 03:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Tool review</title>
      <link>https://blog.example.com/post-3</link>
      <description>Body of the third article.</description>
      <pubDate>Wed, 13 Aug 2026 04:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


def _sample_rss_many(n: int) -> str:
    """Build an RSS feed with `n` identical items."""
    items = "\n".join(
        f"""    <item>
      <title>Post number {i}</title>
      <link>https://blog.example.com/post-{i}</link>
      <description>Body number {i}.</description>
      <pubDate>Wed, 13 Aug 2026 0{i}:00:00 GMT</pubDate>
    </item>"""
        for i in range(n)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0"><channel>'
        "<title>Many AI</title><link>https://blog.example.com/</link>"
        f"<description>x</description>{items}</channel></rss>"
    )


def _patch_web_sources(monkeypatch, sources):
    import app.pipeline.collectors.web as web_module
    monkeypatch.setattr(web_module, "DEFAULT_SOURCES", list(sources))
    monkeypatch.setattr(web_module, "DEFAULT_FEEDS", list(sources))


@pytest.mark.asyncio
async def test_collect_web_happy_path(monkeypatch):
    """One feed returns 3 entries -> 3 RawItems with proper fields."""
    _patch_settings(monkeypatch)
    import app.pipeline.collectors.web as web_module

    _patch_web_sources(monkeypatch, [("Example AI", "https://blog.example.com/feed.xml")])

    import respx
    with respx.mock(assert_all_called=False) as router:
        router.get("https://blog.example.com/feed.xml").respond(
            status_code=200, text=_SAMPLE_RSS_3
        )
        items = await web_module.collect_web()

    assert len(items) == 3
    assert all(it.sourceKey == SourceKey.WEB for it in items)
    assert all(it.sourceName == "Example AI" for it in items)
    titles = {it.title for it in items}
    assert titles == {"Agent framework released", "New open-source LLM", "Tool review"}
    for it in items:
        assert it.sourceUrl.startswith("https://blog.example.com/post-")
        assert it.extra["source_index"] == "https://blog.example.com/feed.xml"
    # ISO timestamp from GMT pubDate.
    assert items[0].publishedAt.startswith("2026-08-13T02:00:00")
    # rawText populated from description.
    assert items[0].rawText == "Body of the first article."


@pytest.mark.asyncio
async def test_collect_web_per_source_cap(monkeypatch):
    """Feed returns 8 entries but only PER_SOURCE_LIMIT (5) are picked."""
    _patch_settings(monkeypatch)
    import app.pipeline.collectors.web as web_module

    _patch_web_sources(monkeypatch, [("Many AI", "https://blog.example.com/feed.xml")])

    import respx
    with respx.mock(assert_all_called=False) as router:
        router.get("https://blog.example.com/feed.xml").respond(
            status_code=200, text=_sample_rss_many(8)
        )
        items = await web_module.collect_web()

    assert len(items) == 5
    assert all(it.sourceName == "Many AI" for it in items)
    titles = sorted(it.title for it in items)
    assert titles == ["Post number 0", "Post number 1", "Post number 2", "Post number 3", "Post number 4"]


@pytest.mark.asyncio
async def test_collect_web_source_404_others_continue(monkeypatch):
    """One feed 404s -> other feed still returns its items (FR-007a)."""
    _patch_settings(monkeypatch)
    import app.pipeline.collectors.web as web_module

    _patch_web_sources(
        monkeypatch,
        [
            ("Down AI", "https://down.example.com/feed.xml"),
            ("OK AI", "https://ok.example.com/feed.xml"),
        ],
    )

    import respx
    with respx.mock(assert_all_called=False) as router:
        router.get("https://down.example.com/feed.xml").respond(status_code=404)
        router.get("https://ok.example.com/feed.xml").respond(
            status_code=200, text=_SAMPLE_RSS_3
        )
        items = await web_module.collect_web()

    assert len(items) == 3
    # Items came from the OK feed, not the down one. The OK AI source name is
    # set by the feed list; entry URLs come from the RSS payload.
    assert all(it.sourceName == "OK AI" for it in items)
    assert all("blog.example.com" in it.sourceUrl for it in items)


@pytest.mark.asyncio
async def test_collect_web_xml_parse_error_skipped(monkeypatch):
    """One feed returns garbage XML -> skipped; the other still returns items."""
    _patch_settings(monkeypatch)
    import app.pipeline.collectors.web as web_module

    _patch_web_sources(
        monkeypatch,
        [
            ("Broken AI", "https://broken.example.com/feed.xml"),
            ("Good AI", "https://good.example.com/feed.xml"),
        ],
    )

    import respx
    with respx.mock(assert_all_called=False) as router:
        router.get("https://broken.example.com/feed.xml").respond(
            status_code=200, text="<<<not xml<<< garbage"
        )
        router.get("https://good.example.com/feed.xml").respond(
            status_code=200, text=_SAMPLE_RSS_3
        )
        items = await web_module.collect_web()

    # Broken feed yields 0 (no entries parsed); good feed yields 3.
    assert len(items) == 3
    assert all(it.sourceName == "Good AI" for it in items)


@pytest.mark.asyncio
async def test_collect_web_all_failures_returns_empty(monkeypatch):
    """All feeds fail (HTTP 500) -> empty list, no raise."""
    _patch_settings(monkeypatch)
    import app.pipeline.collectors.web as web_module

    _patch_web_sources(
        monkeypatch,
        [
            ("Down A", "https://down-a.example.com/feed.xml"),
            ("Down B", "https://down-b.example.com/feed.xml"),
        ],
    )

    import respx
    with respx.mock(assert_all_called=False) as router:
        router.get("https://down-a.example.com/feed.xml").respond(status_code=500)
        router.get("https://down-b.example.com/feed.xml").respond(status_code=500)
        items = await web_module.collect_web()

    assert items == []


# ---------- X collector (twitter-cli subprocess) ----------

def _tweet_dict(tid: str, text: str, screen_name: str = "x", age_hours: float = 2.0) -> dict:
    """Build a twitter-cli-shaped tweet dict, published `age_hours` ago (UTC)."""
    created = datetime.now(tz=timezone.utc) - timedelta(hours=age_hours)
    return {
        "id": tid,
        "text": text,
        "author": {
            "id": "1",
            "name": screen_name,
            "screenName": screen_name,
            "profileImageUrl": "",
            "verified": False,
        },
        "metrics": {"likes": 0, "retweets": 0, "replies": 0, "quotes": 0, "views": 0, "bookmarks": 0},
        "createdAt": created.strftime("%a %b %d %H:%M:%S +0000 %Y"),
        "createdAtISO": created.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        "createdAtLocal": created.strftime("%Y-%m-%d %H:%M:%S"),
        "media": [],
        "urls": [],
        "isRetweet": False,
        "retweetedBy": None,
        "lang": "en",
        "score": None,
    }


class _FakeTwitterProc:
    """Fake asyncio subprocess for twitter-cli invocations."""

    def __init__(self, stdout_bytes: bytes, returncode: int = 0):
        self._stdout = stdout_bytes
        self.returncode = returncode
        self.killed = False

    async def communicate(self):
        return (self._stdout, b"")

    def kill(self):
        self.killed = True

    async def wait(self):
        return self.returncode


def _install_twitter_cli_stub(monkeypatch, account_to_outcome: dict) -> dict:
    """Patch asyncio.create_subprocess_exec inside the x_rsshub module.

    `account_to_outcome` maps account -> one of:
      {"envelope": [<tweet_dict>, ...]}   → success wrapped in agent schema (default)
      {"stdout": <bytes>}                 → success with that raw stdout
      {"returncode": N}                   → non-zero exit (N != 0)
      {"invalid_json": True}              → stdout is invalid JSON
      {"raise": exc}                      → spawn raises (e.g. FileNotFoundError)

    Returns a dict with `call_log` (list of argv lists per spawn).
    """
    import app.pipeline.collectors.x_rsshub as x_module

    call_log: list[list[str]] = []

    async def fake_exec(*args, **kwargs):
        call_log.append(list(args))
        # args[0]="twitter" args[1]="user-posts" args[2]=account ...
        if len(args) < 3:
            raise AssertionError(f"unexpected twitter-cli args: {args!r}")
        account = args[2]
        outcome = account_to_outcome.get(account, {"envelope": []})

        if "raise" in outcome:
            raise outcome["raise"]
        if "invalid_json" in outcome:
            return _FakeTwitterProc(b"not valid json {{{", returncode=0)
        if "returncode" in outcome:
            return _FakeTwitterProc(b"", returncode=int(outcome["returncode"]))
        if "stdout" in outcome:
            return _FakeTwitterProc(outcome["stdout"], returncode=0)

        envelope = {"ok": True, "schema_version": "1", "data": outcome.get("envelope", [])}
        return _FakeTwitterProc(json.dumps(envelope).encode("utf-8"), returncode=0)

    monkeypatch.setattr(x_module.asyncio, "create_subprocess_exec", fake_exec)
    return {"call_log": call_log}


@pytest.mark.asyncio
async def test_collect_x_no_cookies_returns_empty(monkeypatch):
    """Missing TWITTER_AUTH_TOKEN/CT0 (and browser fallback off) → silent skip."""
    _patch_settings(monkeypatch, AIDAILY_X_ACCOUNTS="karpathy,ylecun")
    monkeypatch.delenv("TWITTER_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("TWITTER_CT0", raising=False)
    monkeypatch.delenv("AIDAILY_X_ALLOW_BROWSER_COOKIES", raising=False)

    import app.pipeline.collectors.x_rsshub as x_module

    # Real backend/.env may carry cookies — this test simulates their absence.
    monkeypatch.setattr(x_module, "_dotenv_loaded", True)

    spawn_called = []

    async def boom(*a, **kw):
        spawn_called.append(a)
        raise AssertionError("should not spawn when cookies are missing")

    monkeypatch.setattr(x_module.asyncio, "create_subprocess_exec", boom)

    from app.pipeline.collectors.x_rsshub import collect_x_rsshub

    items = await collect_x_rsshub()
    assert items == []
    assert spawn_called == []


@pytest.mark.asyncio
async def test_collect_x_browser_cookie_fallback_spawns(monkeypatch):
    """AIDAILY_X_ALLOW_BROWSER_COOKIES=1 → spawn proceeds despite missing env cookies."""
    _patch_settings(monkeypatch, AIDAILY_X_ACCOUNTS="karpathy")
    monkeypatch.delenv("TWITTER_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("TWITTER_CT0", raising=False)
    monkeypatch.setenv("AIDAILY_X_ALLOW_BROWSER_COOKIES", "1")

    install = _install_twitter_cli_stub(
        monkeypatch,
        {"karpathy": {"envelope": [_tweet_dict("1", "hello world", "karpathy")]}},
    )

    from app.pipeline.collectors.x_rsshub import collect_x_rsshub

    items = await collect_x_rsshub()
    assert len(items) == 1
    assert install["call_log"], "twitter-cli must be spawned under browser-cookie fallback"


@pytest.mark.asyncio
async def test_collect_x_happy_path(monkeypatch):
    """2 accounts x 3 tweets each → 6 RawItems with proper field mapping."""
    _patch_settings(monkeypatch, AIDAILY_X_ACCOUNTS="acc_a,acc_b")
    monkeypatch.setenv("TWITTER_AUTH_TOKEN", "tok")
    monkeypatch.setenv("TWITTER_CT0", "ct0")

    install = _install_twitter_cli_stub(
        monkeypatch,
        {
            "acc_a": {"envelope": [
                _tweet_dict("100", "agent framework release from acc_a", "acc_a"),
                _tweet_dict("101", "second tweet", "acc_a"),
                _tweet_dict("102", "third tweet about LLMs", "acc_a"),
            ]},
            "acc_b": {"envelope": [
                _tweet_dict("200", "tweet one from acc_b", "acc_b"),
                _tweet_dict("201", "tweet two from acc_b", "acc_b"),
                _tweet_dict("202", "tweet three from acc_b", "acc_b"),
            ]},
        },
    )

    from app.pipeline.collectors.x_rsshub import collect_x_rsshub

    items = await collect_x_rsshub()

    assert len(items) == 6
    # spawn args: each call uses `twitter user-posts <account> -n 3 --json`
    cli_args = install["call_log"]
    assert len(cli_args) == 2
    assert cli_args[0][1:3] == ["user-posts", "acc_a"]
    assert cli_args[1][1:3] == ["user-posts", "acc_b"]
    assert cli_args[0][3:] == ["-n", "3", "--json"]

    by_account = {"acc_a": [], "acc_b": []}
    for it in items:
        by_account[it.extra["author"]].append(it)

    a0 = by_account["acc_a"][0]
    assert a0.sourceKey == SourceKey.X
    assert a0.sourceName == "x.com/@acc_a"
    assert a0.sourceUrl == "https://x.com/acc_a/status/100"
    assert a0.title == "agent framework release from acc_a"[:80]
    assert a0.rawText == "agent framework release from acc_a"
    # publishedAt mirrors the tweet's createdAtISO (fixture default: 2h ago)
    parsed_iso = datetime.fromisoformat(a0.publishedAt)
    age_h = (datetime.now(tz=timezone.utc) - parsed_iso).total_seconds() / 3600
    assert 0 < age_h < 3
    assert a0.extra == {
        "author": "acc_a", "tweet_id": "100", "likes": 0, "views": 0, "retweets": 0,
    }


@pytest.mark.asyncio
async def test_collect_x_drops_tweets_older_than_72h(monkeypatch):
    """Tweets published more than 72h ago are dropped at collection time."""
    _patch_settings(monkeypatch, AIDAILY_X_ACCOUNTS="acc")
    monkeypatch.setenv("TWITTER_AUTH_TOKEN", "tok")
    monkeypatch.setenv("TWITTER_CT0", "ct0")

    fresh = _tweet_dict("1", "fresh take", "acc", age_hours=1.0)
    stale = _tweet_dict("2", "stale take from last week", "acc", age_hours=100.0)

    _install_twitter_cli_stub(monkeypatch, {"acc": {"envelope": [fresh, stale]}})

    from app.pipeline.collectors.x_rsshub import collect_x_rsshub

    items = await collect_x_rsshub()
    assert [i.extra["tweet_id"] for i in items] == ["1"]


@pytest.mark.asyncio
async def test_collect_x_tweet_without_parseable_timestamp_kept(monkeypatch):
    """No parseable timestamp → kept (aligned with web.py's soft-window tolerance)."""
    _patch_settings(monkeypatch, AIDAILY_X_ACCOUNTS="acc")
    monkeypatch.setenv("TWITTER_AUTH_TOKEN", "tok")
    monkeypatch.setenv("TWITTER_CT0", "ct0")

    undated = _tweet_dict("3", "mysterious undated tweet", "acc")
    undated.pop("createdAtISO")
    undated.pop("createdAt")
    undated.pop("createdAtLocal")

    _install_twitter_cli_stub(monkeypatch, {"acc": {"envelope": [undated]}})

    from app.pipeline.collectors.x_rsshub import collect_x_rsshub

    items = await collect_x_rsshub()
    assert [i.extra["tweet_id"] for i in items] == ["3"]


@pytest.mark.asyncio
async def test_collect_x_stores_engagement_snapshot(monkeypatch):
    """likes/views/retweets from twitter-cli metrics land in extra (spec 004)."""
    _patch_settings(monkeypatch, AIDAILY_X_ACCOUNTS="k")
    monkeypatch.setenv("TWITTER_AUTH_TOKEN", "tok")
    monkeypatch.setenv("TWITTER_CT0", "ct0")

    tweet = _tweet_dict("7", "viral take", "k")
    tweet["metrics"] = {
        "likes": 149_658, "retweets": 12_000, "views": 27_926_916,
        "replies": 500, "quotes": 40, "bookmarks": 900,
    }
    _install_twitter_cli_stub(monkeypatch, {"k": {"envelope": [tweet]}})

    from app.pipeline.collectors.x_rsshub import collect_x_rsshub

    items = await collect_x_rsshub()
    assert items[0].extra["likes"] == 149_658
    assert items[0].extra["retweets"] == 12_000
    assert items[0].extra["views"] == 27_926_916
    # Only the three agreed keys — replies/quotes/bookmarks stay out.
    assert "replies" not in items[0].extra
    assert "quotes" not in items[0].extra


@pytest.mark.asyncio
async def test_collect_x_missing_or_invalid_metrics_omitted(monkeypatch):
    """Absent metrics dict or non-numeric values → keys omitted, no defaults."""
    _patch_settings(monkeypatch, AIDAILY_X_ACCOUNTS="a,b")
    monkeypatch.setenv("TWITTER_AUTH_TOKEN", "tok")
    monkeypatch.setenv("TWITTER_CT0", "ct0")

    no_metrics = _tweet_dict("1", "plain tweet", "a")
    no_metrics.pop("metrics")
    garbage = _tweet_dict("2", "weird metrics", "b")
    garbage["metrics"] = {"likes": "viral", "views": None, "retweets": -5}

    _install_twitter_cli_stub(
        monkeypatch, {"a": {"envelope": [no_metrics]}, "b": {"envelope": [garbage]}}
    )

    from app.pipeline.collectors.x_rsshub import collect_x_rsshub

    items = await collect_x_rsshub()
    by_acc = {i.extra["author"]: i for i in items}
    assert by_acc["a"].extra == {"author": "a", "tweet_id": "1"}
    assert by_acc["b"].extra == {"author": "b", "tweet_id": "2"}


@pytest.mark.asyncio
async def test_collect_x_one_account_fails_other_continues(monkeypatch):
    """One account non-zero exit, other still returns its tweets."""
    _patch_settings(monkeypatch, AIDAILY_X_ACCOUNTS="bad_acc,good_acc")
    monkeypatch.setenv("TWITTER_AUTH_TOKEN", "tok")
    monkeypatch.setenv("TWITTER_CT0", "ct0")

    _install_twitter_cli_stub(
        monkeypatch,
        {
            "bad_acc": {"returncode": 1},
            "good_acc": {"envelope": [_tweet_dict("9", "happy tweet", "good_acc")]},
        },
    )

    from app.pipeline.collectors.x_rsshub import collect_x_rsshub

    items = await collect_x_rsshub()
    assert len(items) == 1
    assert items[0].extra["author"] == "good_acc"
    assert items[0].sourceUrl == "https://x.com/good_acc/status/9"


@pytest.mark.asyncio
async def test_collect_x_json_parse_error_skips_account(monkeypatch):
    """Invalid JSON stdout for one account → that account skipped, others continue."""
    _patch_settings(monkeypatch, AIDAILY_X_ACCOUNTS="broken,ok")
    monkeypatch.setenv("TWITTER_AUTH_TOKEN", "tok")
    monkeypatch.setenv("TWITTER_CT0", "ct0")

    _install_twitter_cli_stub(
        monkeypatch,
        {
            "broken": {"invalid_json": True},
            "ok": {"envelope": [_tweet_dict("5", "valid tweet", "ok")]},
        },
    )

    from app.pipeline.collectors.x_rsshub import collect_x_rsshub

    items = await collect_x_rsshub()
    assert len(items) == 1
    assert items[0].extra["author"] == "ok"


__all__ = []