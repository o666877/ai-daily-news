"""Unit tests for the opencli Reddit bridge (reddit_opencli.py) and the
channel dispatch inside reddit.py.

The bridge shells out to `opencli reddit subreddit <sub> ... -f json` per
subreddit serially (browser tab lease is a shared resource). Dispatch in
reddit.py: probe opencli availability -> bridge; all-subs-fail or probe
failure -> fallback to the Atom .rss path.

Network is never touched: subprocess spawns are stubbed, Atom HTTP is
mocked with respx.
"""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock

import pytest

from app.config import reset_settings_cache
from app.models.meta import SourceKey


def _patch_settings(monkeypatch, **overrides):
    defaults = {
        "AIDAILY_GITHUB_TOKEN": "",
        "AIDAILY_X_RSSHUB_BASE_URL": "",
        "AIDAILY_X_ACCOUNTS": "",
        "AIDAILY_REDDIT_UA": "ai-daily/test",
    }
    defaults.update(overrides)
    for k, v in defaults.items():
        monkeypatch.setenv(k, v)
    reset_settings_cache()


# ---------- fixtures / helpers ----------


def _post_dict(
    *,
    post_id: str = "abc1",
    title: str = "Agent framework discussion",
    score: int = 120,
    comments: int = 34,
    age_hours: float = 1,
    selftext: str = "Long self text about the framework.",
    post_hint: str = "",
    url: str | None = None,
) -> dict:
    """Build one opencli-shaped Reddit post dict (field names verbatim from
    `opencli reddit subreddit -f json` output captured 2026-08-17)."""
    permalink = url or (
        f"https://www.reddit.com/r/TestSub/comments/{post_id}/agent_framework/"
    )
    return {
        "id": post_id,
        "title": title,
        "subreddit": "r/TestSub",
        "author": "someuser",
        "score": score,
        "comments": comments,
        "url": permalink,
        "created_utc": int(time.time()) - int(age_hours * 3600),
        "selftext": selftext,
        "post_hint": post_hint,
        "url_overridden_by_dest": "",
        "preview_image_url": "",
        "gallery_urls": [],
    }


class _FakeProc:
    """Fake asyncio subprocess for opencli invocations."""

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


def _install_opencli_stub(monkeypatch, sub_to_outcome: dict) -> dict:
    """Patch asyncio.create_subprocess_exec inside reddit_opencli.

    `sub_to_outcome` maps subreddit -> one of:
      {"posts": [<post_dict>, ...]}  → success, plain JSON array on stdout
      {"returncode": N}              → non-zero exit
      {"invalid_json": True}         → stdout is not JSON
      {"raise": exc}                 → spawn raises (binary missing etc.)

    Returns {"call_log": [argv, ...]}.
    """
    import app.pipeline.collectors.reddit_opencli as oc

    call_log: list[list[str]] = []

    async def fake_exec(*args, **kwargs):
        call_log.append(list(args))
        # argv: ["opencli", "reddit", "subreddit", <sub>, ...]
        sub = args[3]
        outcome = sub_to_outcome.get(sub, {"posts": []})
        if "raise" in outcome:
            raise outcome["raise"]
        if "invalid_json" in outcome:
            return _FakeProc(b"not json {{{", returncode=0)
        if "returncode" in outcome:
            return _FakeProc(b"", returncode=int(outcome["returncode"]))
        payload = json.dumps(outcome.get("posts", [])).encode("utf-8")
        return _FakeProc(payload, returncode=0)

    monkeypatch.setattr(oc.asyncio, "create_subprocess_exec", fake_exec)
    return {"call_log": call_log}


# ---------- bridge: happy path & field mapping ----------


@pytest.mark.asyncio
async def test_opencli_happy_path_field_mapping(monkeypatch):
    """Posts arrive with score/comments/selftext mapped into RawItem + extra."""
    _patch_settings(monkeypatch)

    import app.pipeline.collectors.reddit_opencli as oc

    posts = {
        "MachineLearning": {"posts": [
            _post_dict(post_id="aa11", score=358, comments=48,
                       selftext="body about agents", post_hint="link"),
        ]},
        "localLLaMA": {"posts": [
            _post_dict(post_id="bb22", score=42, comments=7, selftext=""),
        ]},
    }
    install = _install_opencli_stub(monkeypatch, posts)
    monkeypatch.setattr(oc.shutil, "which", lambda _: "C:/fake/opencli.CMD")

    items = await oc.collect_via_opencli(["MachineLearning", "localLLaMA"])

    assert len(items) == 2
    assert all(i.sourceKey == SourceKey.REDDIT for i in items)
    assert all(i.sourceName.startswith("reddit.com/r/") for i in items)

    ml = next(i for i in items if i.extra["post_id"] == "aa11")
    assert ml.title == "Agent framework discussion"
    assert ml.sourceUrl.endswith("/comments/aa11/agent_framework/")
    assert ml.rawText == "body about agents"
    assert ml.extra["subreddit"] == "MachineLearning"
    assert ml.extra["score"] == 358
    assert ml.extra["num_comments"] == 48
    assert ml.extra["post_hint"] == "link"
    assert ml.publishedAt.startswith("20")

    # Empty selftext → rawText falls back to title.
    ll = next(i for i in items if i.extra["post_id"] == "bb22")
    assert ll.rawText == "Agent framework discussion"
    assert "post_hint" not in ll.extra  # empty hint omitted

    # argv shape: serial, one call per sub, top/week/limit 10, json, background.
    argvs = install["call_log"]
    assert len(argvs) == 2
    assert argvs[0][1:4] == ["reddit", "subreddit", "MachineLearning"]
    assert argvs[0][4:] == [
        "--sort", "top", "--time", "week", "--limit", "10",
        "-f", "json", "--window", "background",
    ]


@pytest.mark.asyncio
async def test_opencli_serial_execution(monkeypatch):
    """Sub calls never overlap: call N+1 starts only after N finishes."""
    _patch_settings(monkeypatch)

    import app.pipeline.collectors.reddit_opencli as oc

    active = {"now": 0}
    max_overlap = {"v": 0}

    class _SlowProc(_FakeProc):
        async def communicate(self):
            active["now"] += 1
            max_overlap["v"] = max(max_overlap["v"], active["now"])
            import asyncio
            await asyncio.sleep(0.01)
            active["now"] -= 1
            return (self._stdout, b"")

    def make_exec(outcome_by_sub):
        async def fake_exec(*args, **kwargs):
            sub = args[3]
            payload = json.dumps(outcome_by_sub.get(sub, {"posts": []})["posts"])
            return _SlowProc(payload.encode())
        return fake_exec

    monkeypatch.setattr(
        oc.asyncio, "create_subprocess_exec",
        make_exec({"A": {"posts": [_post_dict()]}, "B": {"posts": [_post_dict()]}}),
    )
    monkeypatch.setattr(oc.shutil, "which", lambda _: "opencli")

    items = await oc.collect_via_opencli(["A", "B"])
    assert len(items) == 2
    assert max_overlap["v"] == 1, "subprocess calls must be strictly serial"


# ---------- bridge: filters & failure isolation ----------


@pytest.mark.asyncio
async def test_opencli_stale_posts_filtered(monkeypatch):
    """Posts older than 72h are dropped; fresh ones kept."""
    _patch_settings(monkeypatch)
    import app.pipeline.collectors.reddit_opencli as oc

    _install_opencli_stub(monkeypatch, {"S": {"posts": [
        _post_dict(post_id="fresh", age_hours=1),
        _post_dict(post_id="stale", age_hours=100),
    ]}})
    monkeypatch.setattr(oc.shutil, "which", lambda _: "opencli")

    items = await oc.collect_via_opencli(["S"])
    assert [i.extra["post_id"] for i in items] == ["fresh"]


@pytest.mark.asyncio
async def test_opencli_post_without_title_or_url_skipped(monkeypatch):
    """Posts missing title or url carry no value — skipped, others kept."""
    _patch_settings(monkeypatch)
    import app.pipeline.collectors.reddit_opencli as oc

    bad_no_title = _post_dict(post_id="nt"); bad_no_title["title"] = ""
    bad_no_url = _post_dict(post_id="nu"); bad_no_url["url"] = ""
    _install_opencli_stub(monkeypatch, {"S": {"posts": [
        bad_no_title, bad_no_url, _post_dict(post_id="ok"),
    ]}})
    monkeypatch.setattr(oc.shutil, "which", lambda _: "opencli")

    items = await oc.collect_via_opencli(["S"])
    assert [i.extra["post_id"] for i in items] == ["ok"]


@pytest.mark.asyncio
async def test_opencli_one_sub_fails_other_continues(monkeypatch):
    """Non-zero exit on one sub is skipped; the other still returns posts."""
    _patch_settings(monkeypatch)
    import app.pipeline.collectors.reddit_opencli as oc

    _install_opencli_stub(monkeypatch, {
        "Bad": {"returncode": 1},
        "Good": {"posts": [_post_dict(post_id="g1")]},
    })
    monkeypatch.setattr(oc.shutil, "which", lambda _: "opencli")

    items = await oc.collect_via_opencli(["Bad", "Good"])
    assert [i.extra["post_id"] for i in items] == ["g1"]


@pytest.mark.asyncio
async def test_opencli_invalid_json_skipped(monkeypatch):
    """Unparseable stdout for one sub → skipped, others continue."""
    _patch_settings(monkeypatch)
    import app.pipeline.collectors.reddit_opencli as oc

    _install_opencli_stub(monkeypatch, {
        "Broken": {"invalid_json": True},
        "Ok": {"posts": [_post_dict(post_id="o1")]},
    })
    monkeypatch.setattr(oc.shutil, "which", lambda _: "opencli")

    items = await oc.collect_via_opencli(["Broken", "Ok"])
    assert [i.extra["post_id"] for i in items] == ["o1"]


@pytest.mark.asyncio
async def test_opencli_rawtext_capped(monkeypatch):
    """Giant selftext is capped so the LLM input stays bounded."""
    _patch_settings(monkeypatch)
    import app.pipeline.collectors.reddit_opencli as oc

    _install_opencli_stub(monkeypatch, {"S": {"posts": [
        _post_dict(post_id="big", selftext="x" * 10_000),
    ]}})
    monkeypatch.setattr(oc.shutil, "which", lambda _: "opencli")

    items = await oc.collect_via_opencli(["S"])
    assert len(items[0].rawText) <= 4000


def test_opencli_available_requires_binary(monkeypatch):
    """opencli_available() is a pure PATH probe — no subprocess."""
    _patch_settings(monkeypatch)
    import app.pipeline.collectors.reddit_opencli as oc

    # conftest sets the kill switch globally — lift it for the probe cases.
    monkeypatch.delenv("AIDAILY_REDDIT_DISABLE_OPENCLI", raising=False)
    monkeypatch.setattr(oc.shutil, "which", lambda _: None)
    assert oc.opencli_available() is False
    monkeypatch.setattr(oc.shutil, "which", lambda _: "/fake/opencli.CMD")
    assert oc.opencli_available() is True
    # Kill switch wins even when the binary is present.
    monkeypatch.setenv("AIDAILY_REDDIT_DISABLE_OPENCLI", "1")
    assert oc.opencli_available() is False


# ---------- dispatch inside reddit.py ----------


def _atom_feed_minimal(title: str, permalink: str) -> str:
    """Minimal one-entry Atom doc for the fallback path."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom"><title>t</title>'
        f"<entry><title>{title}</title>"
        f'<link rel="alternate" href="{permalink}" />'
        f"<id>{permalink}</id>"
        "<published>2026-08-18T00:00:00+00:00</published>"
        "<updated>2026-08-18T00:00:00+00:00</updated>"
        "</entry></feed>"
    )


@pytest.mark.asyncio
async def test_dispatch_probe_fail_uses_atom(monkeypatch):
    """opencli binary absent → Atom path serves the request."""
    _patch_settings(monkeypatch)
    from app.pipeline.collectors import reddit as reddit_mod

    monkeypatch.setattr(reddit_mod, "SUBREDDITS", ["ProbeSub"])
    monkeypatch.setattr(
        reddit_mod.reddit_opencli, "opencli_available", lambda: False
    )
    bridge = AsyncMock(return_value=[])
    monkeypatch.setattr(reddit_mod.reddit_opencli, "collect_via_opencli", bridge)

    import respx
    with respx.mock(assert_all_called=False) as router:
        router.get("https://www.reddit.com/r/ProbeSub/top/.rss").respond(
            status_code=200, text=_atom_feed_minimal(
                "Atom post", "https://www.reddit.com/r/ProbeSub/comments/ap1/atom_post/"
            )
        )
        items = await reddit_mod.collect_reddit()

    assert len(items) == 1
    assert items[0].title == "Atom post"
    bridge.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_kill_switch_skips_bridge(monkeypatch):
    """AIDAILY_REDDIT_DISABLE_OPENCLI=1 (set globally in conftest) → the real
    opencli_available() returns False, dispatch goes straight to Atom and the
    bridge is never awaited."""
    _patch_settings(monkeypatch)
    from app.pipeline.collectors import reddit as reddit_mod

    monkeypatch.setattr(reddit_mod, "SUBREDDITS", ["SwitchSub"])

    bridge = AsyncMock(side_effect=AssertionError("bridge must not run"))
    monkeypatch.setattr(reddit_mod.reddit_opencli, "collect_via_opencli", bridge)

    import respx
    with respx.mock(assert_all_called=False) as router:
        router.get("https://www.reddit.com/r/SwitchSub/top/.rss").respond(
            status_code=200, text=_atom_feed_minimal(
                "Kill switch post", "https://www.reddit.com/r/SwitchSub/comments/ks1/post/"
            )
        )
        items = await reddit_mod.collect_reddit()

    assert len(items) == 1
    assert items[0].title == "Kill switch post"
    bridge.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_all_subs_fail_falls_back_to_atom(monkeypatch):
    """Bridge available but every sub fails → Atom fallback kicks in."""
    _patch_settings(monkeypatch)
    from app.pipeline.collectors import reddit as reddit_mod

    monkeypatch.setattr(reddit_mod, "SUBREDDITS", ["FailSub"])
    monkeypatch.setattr(
        reddit_mod.reddit_opencli, "opencli_available", lambda: True
    )
    monkeypatch.setattr(
        reddit_mod.reddit_opencli, "collect_via_opencli", AsyncMock(return_value=[])
    )

    import respx
    with respx.mock(assert_all_called=False) as router:
        route = router.get("https://www.reddit.com/r/FailSub/top/.rss").respond(
            status_code=200, text=_atom_feed_minimal(
                "Fallback post", "https://www.reddit.com/r/FailSub/comments/fb1/post/"
            )
        )
        items = await reddit_mod.collect_reddit()

    assert len(items) == 1
    assert items[0].title == "Fallback post"
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_dispatch_opencli_success_skips_atom(monkeypatch):
    """Bridge returns items → Atom HTTP is never touched."""
    _patch_settings(monkeypatch)
    from app.pipeline.collectors import reddit as reddit_mod

    monkeypatch.setattr(reddit_mod, "SUBREDDITS", ["WinSub"])
    monkeypatch.setattr(
        reddit_mod.reddit_opencli, "opencli_available", lambda: True
    )

    from app.models.article import RawItem
    bridged = RawItem(
        sourceKey=SourceKey.REDDIT,
        sourceName="reddit.com/r/WinSub",
        sourceUrl="https://www.reddit.com/r/WinSub/comments/w1/post/",
        title="Bridged post",
        rawText="body",
        publishedAt="2026-08-18T00:00:00+00:00",
        extra={"subreddit": "WinSub", "post_id": "w1", "score": 10, "num_comments": 2},
    )
    monkeypatch.setattr(
        reddit_mod.reddit_opencli,
        "collect_via_opencli",
        AsyncMock(return_value=[bridged]),
    )

    import respx
    with respx.mock(assert_all_called=False) as router:
        route = router.get("https://www.reddit.com/r/WinSub/top/.rss").respond(
            status_code=200, text=_atom_feed_minimal("x", "https://example.com/y")
        )
        items = await reddit_mod.collect_reddit()

    assert len(items) == 1
    assert items[0].title == "Bridged post"
    assert items[0].extra["score"] == 10
    assert route.call_count == 0, "atom must not be hit when bridge succeeds"


__all__ = []
