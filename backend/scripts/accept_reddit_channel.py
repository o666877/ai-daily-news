"""Acceptance run for the Reddit channel dispatch (opencli bridge + Atom fallback).

Usage:
  python scripts/accept_reddit_channel.py            # round 1: opencli on
  AIDAILY_REDDIT_DISABLE_OPENCLI=1 python ...        # round 2: kill switch -> atom

Prints channel, per-sub counts, and extra-field samples; exit 0 if any
channel produced items.
"""

from __future__ import annotations

import asyncio
import logging
import os

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

from app.pipeline.collectors import reddit as reddit_mod  # noqa: E402
from app.pipeline.collectors import reddit_opencli  # noqa: E402


async def main() -> int:
    print("kill switch env:", os.environ.get("AIDAILY_REDDIT_DISABLE_OPENCLI", "<unset>"))
    print("opencli_available():", reddit_opencli.opencli_available())
    print(f"subs: {reddit_mod.SUBREDDITS}")

    items = await reddit_mod.collect_reddit()

    print(f"\ntotal items: {len(items)}")
    by_sub: dict[str, int] = {}
    for it in items:
        by_sub[it.extra.get("subreddit", "?")] = by_sub.get(it.extra.get("subreddit", "?"), 0) + 1
    print("per-sub:", by_sub)

    scored = [it for it in items if "score" in it.extra]
    print(f"items with score metadata: {len(scored)} / {len(items)}")
    for it in items[:3]:
        print(f"  - [{it.extra.get('subreddit')}] {it.title[:50]}")
        print(f"    extra keys: {sorted(it.extra.keys())}")
        print(f"    score={it.extra.get('score')} comments={it.extra.get('num_comments')} hint={it.extra.get('post_hint')!r}")

    if not items:
        print("NO ITEMS — check channel logs above")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
