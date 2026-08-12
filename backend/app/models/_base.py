"""Pydantic base mix-ins: CamelCase alias generator + shared model_config."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


def to_camel_case(snake: str) -> str:
    """Convert snake_case → camelCase (RFC compliant)."""
    return to_camel(snake)


class CamelModel(BaseModel):
    """Base that serializes snake_case fields as camelCase for API contracts.

    Per contracts/README.md the API uses camelCase JSON (e.g. `issueId`,
    `publishedAt`, `readingMinutes`). Internal Python keeps snake_case;
    aliases bridge the two.
    """

    model_config = ConfigDict(
        alias_generator=to_camel_case,
        populate_by_name=True,
        from_attributes=True,
        extra="ignore",
    )


__all__ = ["CamelModel", "to_camel_case"]
