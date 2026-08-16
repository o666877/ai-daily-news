"""T077: ShareService — generate and look up shareable article cards.

- `generate(article_id)`:
    - Verify the article exists (else raise ArticleNotFoundError → business 2001).
    - Create a new ShareCardORM row with shareId = `shr_<8hex>` (secrets.token_hex(4)),
      articleTitle snapshotted from Article.title, cardUrl = `{host}/share/{shareId}`.
    - The same articleId may produce multiple shareIds (no dedup; lets us count shares).
- `get_by_id(share_id)`: look up an existing share card.
"""

from __future__ import annotations

import secrets

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.infra.errors import ArticleNotFoundError
from app.models.article import ArticleORM
from app.models.share_card import ShareCardORM


def _new_share_id() -> str:
    """Return a fresh shareId matching `^shr_[0-9a-f]{8}$`."""
    return f"shr_{secrets.token_hex(4)}"


class ShareService:
    """Stateless service backed by a single async session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def generate(self, article_id: str) -> ShareCardORM:
        """Create a new share card for the given article.

        Raises ArticleNotFoundError (business code 2001) if the article
        does not exist or has been deleted.
        """
        article = await self._session.get(ArticleORM, article_id)
        if article is None:
            raise ArticleNotFoundError(f"文章不存在: {article_id}")

        share_id = _new_share_id()
        host = get_settings().host
        # cardUrl uses host (configured) so that the same value renders correctly
        # when the user pastes it from any device. Production deployments override
        # AIDAILY_HOST with the public origin.
        card_url = f"{host}/share/{share_id}"

        card = ShareCardORM(
            share_id=share_id,
            article_id=article.id,
            article_title=article.title,  # snapshot — copy now, not a reference
            card_url=card_url,
            created_at=None,  # let default fire at flush
        )
        self._session.add(card)
        await self._session.commit()
        await self._session.refresh(card)
        return card

    async def get_by_id(self, share_id: str) -> ShareCardORM | None:
        """Return the ShareCard row or None."""
        return await self._session.get(ShareCardORM, share_id)


__all__ = ["ShareService"]
