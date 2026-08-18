"""Metadata: Source + Type enums and `/meta` response schema.

4 fixed source keys + 5 type keys (commentary added in specs/005 as the
opinion/news catch-all; tools reverted to pure tooling). These constants are
the single source of truth — never hardcode in API or frontend.
"""

from __future__ import annotations

from enum import Enum

from app.models._base import CamelModel


class SourceKey(str, Enum):
    X = "x"
    GITHUB = "github"
    REDDIT = "reddit"
    WEB = "web"


class TypeKey(str, Enum):
    AGENT = "agent"
    SELF_IMPROVE = "self_improve"
    OPEN_SOURCE = "open_source"
    TOOLS = "tools"
    COMMENTARY = "commentary"


class Source(CamelModel):
    """Source metadata entry."""

    key: SourceKey
    name: str
    short: str
    icon: str
    description: str


class Type(CamelModel):
    """Type metadata entry."""

    key: TypeKey
    name: str
    shortName: str


class MetaOut(CamelModel):
    """GET /meta response shape."""

    sources: list[Source]
    types: list[Type]


# ---------------------------------------------------------------------------
# Static metadata (single source of truth)
# ---------------------------------------------------------------------------

SOURCES: list[Source] = [
    Source(
        key=SourceKey.X,
        name="X (Twitter)",
        short="X",
        icon="x",
        description="前沿哨兵，偶尔发疯但信息最快",
    ),
    Source(
        key=SourceKey.GITHUB,
        name="GitHub",
        short="GitHub",
        icon="github",
        description="仓库动态、新项目、趋势榜单",
    ),
    Source(
        key=SourceKey.REDDIT,
        name="Reddit",
        short="Reddit",
        icon="reddit",
        description="社区热帖与高赞讨论，一手开发者情报",
    ),
    Source(
        key=SourceKey.WEB,
        name="全网聚合",
        short="全网",
        icon="globe",
        description="搜索引擎 + RSS 兜底，不放过漏网之鱼",
    ),
]

TYPES: list[Type] = [
    Type(key=TypeKey.AGENT, name="Agent / 智能体", shortName="Agent"),
    Type(key=TypeKey.SELF_IMPROVE, name="持续学习 / 自我进化", shortName="持续学习"),
    Type(key=TypeKey.OPEN_SOURCE, name="开源项目", shortName="开源"),
    Type(key=TypeKey.TOOLS, name="工具与效率", shortName="工具效率"),
    Type(key=TypeKey.COMMENTARY, name="观点时评", shortName="观点"),
]

SOURCE_KEYS: list[str] = [s.key.value for s in SOURCES]
TYPE_KEYS: list[str] = [t.key.value for t in TYPES]


def is_valid_source(value: str) -> bool:
    return value in SOURCE_KEYS


def is_valid_type(value: str) -> bool:
    return value in TYPE_KEYS


__all__ = [
    "MetaOut",
    "SOURCE_KEYS",
    "SOURCES",
    "Source",
    "SourceKey",
    "TYPE_KEYS",
    "TYPES",
    "Type",
    "TypeKey",
    "is_valid_source",
    "is_valid_type",
]
