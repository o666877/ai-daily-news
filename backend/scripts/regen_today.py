"""Regenerate today's issue with real collectors + real LLM (one-shot)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

from app.pipeline.generator import generate_issue  # noqa: E402


async def main() -> None:
    issue = await generate_issue(date=datetime.now(timezone.utc))
    print(f"FINAL: {issue.id} {issue.status}")


if __name__ == "__main__":
    asyncio.run(main())
