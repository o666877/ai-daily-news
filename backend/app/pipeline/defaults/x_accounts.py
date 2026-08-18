"""Default X (Twitter) KOL account list (T032).

~25 AI community accounts across model/training, agent, infra, and research.
Override via `AIDAILY_X_ACCOUNTS=user1,user2,...` env var.
"""

from __future__ import annotations

DEFAULT_X_ACCOUNTS: list[str] = [
    # Models & training
    "karpathy",
    "ylecun",
    "goodfellow_ian",
    "_jasonwei",
    "rasbt",
    # Agent / 智能体
    "swyx",
    "simonw",
    "miramurati",
    "gdb",
    # Tools & infra
    "sama",
    "emilymenonbender",
    "fchollet",
    # Research institutions
    "AnthropicAI",
    "OpenAI",
    "huggingface",
    "StabilityAI",
    "MistralAI",
    # Research digests & agent tooling
    "_akhaliq",         # daily LLM/agent paper digests — continual-learning / self-improvement papers pass through here
    "jerryjliu0",       # LlamaIndex author — agent tooling ecosystem
    "omarsar0",         # NLP/LLM research roundups
    # Additional KOLs
    "AndrewYNg",
    "iaborodescu",
    "clem",
    "nptacek",
    "hardmaru",
    "ericjang11",
    "kbball",
    "svpino",
]


def get_accounts(override_csv: str | None = None) -> list[str]:
    """Return override list (parsed) or DEFAULT_X_ACCOUNTS."""
    if override_csv and override_csv.strip():
        return [a.strip() for a in override_csv.split(",") if a.strip()]
    return list(DEFAULT_X_ACCOUNTS)


__all__ = ["DEFAULT_X_ACCOUNTS", "get_accounts"]
