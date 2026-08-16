"""Application configuration via pydantic-settings.

Reads all AIDAILY_* environment variables per research.md D5/D6/D7 and
quickstart.md. Provides a singleton `settings` instance.
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_db_path() -> str:
    return str(Path(__file__).resolve().parent.parent / "data" / "aidaily.db")


class Settings(BaseSettings):
    """Strongly-typed env-driven configuration."""

    model_config = SettingsConfigDict(
        env_prefix="AIDAILY_",
        env_file=(
            Path(__file__).resolve().parent.parent / ".env",
            Path(__file__).resolve().parent.parent.parent / ".env",
        ),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ----- LLM -----
    llm_api_key: str = Field(default="", description="Anthropic-compatible API key")
    llm_base_url: str = Field(
        default="https://api.anthropic.com",
        description="LLM endpoint base URL (official or compatible gateway)",
    )
    llm_model: str = Field(
        default="claude-haiku-4-5-20251001",
        description="LLC model identifier",
    )
    llm_daily_budget_usd: float = Field(
        default=2.0,
        ge=0.0,
        description="Daily LLM spend cap in USD; on exceed raises business code 9002",
    )

    # ----- Auth -----
    bearer_token: str = Field(
        default="",
        description="Static Bearer token for write endpoints; auto-generated if empty",
    )

    # ----- Server -----
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8000)
    tz: str = Field(default="Asia/Shanghai")

    # ----- Database -----
    db_path: str = Field(default_factory=_default_db_path)

    # ----- Scheduler -----
    daily_push_time: str = Field(
        default="08:00",
        pattern=r"^([01]\d|2[0-3]):[0-5]\d$",
    )

    # ----- X via RSSHub -----
    x_rsshub_base_url: str = Field(
        default="",
        description="Self-hosted RSSHub URL; empty disables X source",
    )
    x_accounts: str = Field(
        default="",
        description="Comma-separated X usernames; overrides default KOL list",
    )

    # ----- GitHub -----
    github_token: str = Field(default="", description="GitHub PAT for higher rate limit")

    # ----- Reddit -----
    reddit_ua: str = Field(
        default="aidaily/1.0 (research; +https://github.com/aidaily/aidaily)",
        description=(
            "Reddit API user-agent. Reddit 403s the default httpx/python "
            "UA, so this MUST be a descriptive non-default string. Reddit's "
            "guidelines recommend the form `app/version (purpose; +contact)`."
        ),
    )

    @field_validator("bearer_token")
    @classmethod
    def _ensure_bearer_token(cls, v: str) -> str:
        # If empty, generate one deterministically per process; caller logs it once.
        return v

    @property
    def x_account_list(self) -> list[str]:
        """Parse AIDAILY_X_ACCOUNTS into a clean list."""
        if not self.x_accounts.strip():
            return []
        return [a.strip() for a in self.x_accounts.split(",") if a.strip()]

    @property
    def effective_bearer_token(self) -> str:
        """Return configured token or generate a stable random one for the process."""
        if self.bearer_token.strip():
            return self.bearer_token.strip()
        return _generated_token


# Lazy generated fallback token (stable per process).
_generated_token: str = f"auto-{secrets.token_hex(16)}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached singleton Settings instance."""
    return Settings()


def reset_settings_cache() -> None:
    """Test helper: clear the lru_cache so env changes take effect."""
    get_settings.cache_clear()
