"""LLM provider registry.

Single source of truth for the three gateways promptpackage supports in R14:
``openrouter``, ``deepseek``, ``openai``. Adding a fourth (e.g. Together)
should only require appending a new entry here and a model option on the
frontend.

All three speak OpenAI-compatible chat completions, so the differences
captured here are deliberately small:

* ``base_url``       — env-overridable to make local proxies easy.
* ``verify_path``    — the cheapest endpoint that 401s on a bad key.
* ``verify_method``  — usually GET; OpenRouter has a richer ``/key``.
* ``extra_headers``  — OpenRouter wants attribution headers.
* ``summary_model``  — fast/cheap model used for auto-summary jobs.

Keep this module free of Flask globals — values can be looked up at any
point in a request lifecycle, but the only runtime input we read is
``current_app.config``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from flask import current_app


@dataclass(frozen=True)
class ProviderConfig:
    id: str
    label: str
    description: str
    config_base_key: str  # e.g. "OPENROUTER_BASE_URL"
    default_base_url: str
    verify_path: str
    summary_model: str
    extra_headers: dict[str, str]
    docs_url: str

    def base_url(self) -> str:
        configured = current_app.config.get(self.config_base_key)
        return (configured or self.default_base_url).rstrip("/")

    def to_dict(self, *, include_summary: bool = True) -> dict:
        out: dict = {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "docs_url": self.docs_url,
            "verify_path": self.verify_path,
        }
        if include_summary:
            out["summary_model"] = self.summary_model
        return out


_PROVIDERS: dict[str, ProviderConfig] = {
    "openrouter": ProviderConfig(
        id="openrouter",
        label="OpenRouter",
        description=(
            "Single key → 100+ models from OpenAI, Anthropic, Google, Meta, etc. "
            "Easiest way to try multiple providers without juggling separate keys."
        ),
        config_base_key="OPENROUTER_BASE_URL",
        default_base_url="https://openrouter.ai/api/v1",
        verify_path="/key",
        summary_model="openai/gpt-4o-mini",
        extra_headers={
            "HTTP-Referer": "https://promptpackage.local",
            "X-Title": "promptpackage",
        },
        docs_url="https://openrouter.ai/keys",
    ),
    "deepseek": ProviderConfig(
        id="deepseek",
        label="DeepSeek",
        description=(
            "Direct DeepSeek API. Strong reasoning at a low price point. "
            "Use ``deepseek-chat`` for general tasks, ``deepseek-reasoner`` for harder reasoning."
        ),
        config_base_key="DEEPSEEK_BASE_URL",
        default_base_url="https://api.deepseek.com/v1",
        # DeepSeek doesn't expose a /key endpoint; /models is the cheapest auth probe.
        verify_path="/models",
        summary_model="deepseek-chat",
        extra_headers={},
        docs_url="https://platform.deepseek.com/api_keys",
    ),
    "openai": ProviderConfig(
        id="openai",
        label="OpenAI",
        description=(
            "Direct OpenAI API. Use this if you already pay OpenAI and want their "
            "lowest latency. ``gpt-4o-mini`` is a great default."
        ),
        config_base_key="OPENAI_BASE_URL",
        default_base_url="https://api.openai.com/v1",
        verify_path="/models",
        summary_model="gpt-4o-mini",
        extra_headers={},
        docs_url="https://platform.openai.com/api-keys",
    ),
}


SUPPORTED_PROVIDERS: tuple[str, ...] = tuple(_PROVIDERS.keys())
DEFAULT_PROVIDER = "openrouter"


def get_provider(provider_id: str | None) -> ProviderConfig:
    """Look up a provider config; falls back to OpenRouter for back-compat."""
    key = (provider_id or DEFAULT_PROVIDER).strip().lower()
    if key not in _PROVIDERS:
        raise ValueError(f"Unknown provider: {provider_id!r}")
    return _PROVIDERS[key]


def list_providers() -> Iterable[ProviderConfig]:
    return _PROVIDERS.values()


def normalize_provider(provider_id: str | None) -> str:
    """Return a known provider id, mapping ``None`` / unknown → DEFAULT."""
    if not provider_id:
        return DEFAULT_PROVIDER
    key = provider_id.strip().lower()
    if key not in _PROVIDERS:
        return DEFAULT_PROVIDER
    return key


__all__ = [
    "DEFAULT_PROVIDER",
    "ProviderConfig",
    "SUPPORTED_PROVIDERS",
    "get_provider",
    "list_providers",
    "normalize_provider",
]
