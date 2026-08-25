"""IM push log model (specs/006 ticket 03).

One row per (issue, webhook) push attempt. Manual re-pushes append rows
(no unique constraint) — the auto-push dedup reads "any ok row", not
"the latest row".
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db import Base


class ImPushLogORM(Base):
    """Push attempt outcome for one issue × one wecom webhook."""

    __tablename__ = "im_push_logs"
    __table_args__ = (Index("ix_im_push_logs_issue", "issue_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    issue_id: Mapped[str] = mapped_column(
        String(8), ForeignKey("daily_issues.id", ondelete="CASCADE"), nullable=False
    )
    webhook_name: Mapped[str] = mapped_column(String(20), nullable=False)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    errcode: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Sanitized at the source (wecom.py) — never contains the webhook URL.
    errmsg: Mapped[str] = mapped_column(String(200), default="")
    pushed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


__all__ = ["ImPushLogORM"]
