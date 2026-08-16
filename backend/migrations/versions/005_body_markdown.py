"""body: JSON array of paragraphs → single markdown TEXT string (specs/003).

Legacy rows are converted by joining non-empty paragraphs with blank lines —
plain text is valid markdown, so the conversion is lossless.

Revision ID: 005
Revises: 004
Create Date: 2026-08-16
"""

from __future__ import annotations

import json
import logging

import sqlalchemy as sa
from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None

logger = logging.getLogger("aidaily.migration")


def _to_markdown(raw: object) -> str:
    """Coerce a legacy body value (JSON text / list / plain string) to md."""
    if raw is None:
        return ""
    value: object = raw
    if isinstance(raw, (str, bytes, bytearray)):
        try:
            value = json.loads(raw)
        except (ValueError, TypeError):
            return str(raw).strip()
    if isinstance(value, (list, tuple)):
        return "\n\n".join(str(p).strip() for p in value if str(p).strip())
    return str(value).strip()


def upgrade() -> None:
    with op.batch_alter_table("articles") as batch_op:
        batch_op.alter_column("body", existing_type=sa.JSON(), type_=sa.Text())

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, body FROM articles")).fetchall()
    converted = 0
    for row_id, raw_body in rows:
        md = _to_markdown(raw_body)
        conn.execute(
            sa.text("UPDATE articles SET body = :b WHERE id = :i"),
            {"b": md, "i": row_id},
        )
        converted += 1
    if converted:
        logger.info("body_markdown_converted rows=%d", converted)


def downgrade() -> None:
    # Reverse conversion: split md on blank lines back into a JSON array.
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, body FROM articles")).fetchall()
    for row_id, md in rows:
        text = md if isinstance(md, str) else str(md or "")
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        conn.execute(
            sa.text("UPDATE articles SET body = :b WHERE id = :i"),
            {"b": json.dumps(paragraphs, ensure_ascii=False), "i": row_id},
        )
    with op.batch_alter_table("articles") as batch_op:
        batch_op.alter_column("body", existing_type=sa.Text(), type_=sa.JSON())
