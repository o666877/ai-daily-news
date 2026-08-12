"""Pagination query params validator (page ≥ 1, pageSize 1-50).

Raises 1005 (via Pydantic → validation handler) on violations.
"""

from __future__ import annotations

from fastapi import Query
from pydantic import BaseModel, Field


class PageParams(BaseModel):
    """Validated pagination params: page ≥ 1, pageSize 1-50 (default 20)."""

    page: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=50)


def parse_page_params(
    page: int = Query(default=1, ge=1, description="页码，从 1 起"),
    pageSize: int = Query(
        default=20, ge=1, le=50, description="每页条数 1-50，默认 20"
    ),
) -> PageParams:
    """FastAPI dependency: returns validated PageParams."""
    return PageParams(page=page, pageSize=pageSize)


def offset(page_params: PageParams) -> int:
    """Compute SQL OFFSET from page params."""
    return (page_params.page - 1) * page_params.pageSize


__all__ = ["PageParams", "offset", "parse_page_params"]
