"""Pydantic base mix-ins: CamelCase alias generator + shared model_config."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


def to_camel_case(name: str) -> str:
    """Identity-preserving camelCase.

    For names already in camelCase (e.g. "shortName") returns as-is.
    For snake_case names (e.g. "issue_id") converts to "issueId".
    For all-lowercase names with no underscore, returns the name unchanged.
    """
    if "_" in name:
        return to_camel(name)
    return name


class CamelModel(BaseModel):
    """Base that serializes snake_case fields as camelCase for API contracts.

    Per contracts/README.md the API uses camelCase JSON (e.g. `issueId`,
    `publishedAt`, `readingMinutes`). Internal Python keeps snake_case;
    aliases bridge the two. Names that are already camelCase are preserved.
    """

    model_config = ConfigDict(
        alias_generator=to_camel_case,
        populate_by_name=True,
        from_attributes=True,
        extra="ignore",
    )


__all__ = ["CamelModel", "to_camel_case"]
