"""Model pricing table for token cost estimation.

Token prices are in **USD per 1M tokens**, split between prompt and
completion so we can mirror the real billing model each provider uses.
Keep this list small — we only need entries for the models we curate in
the frontend's constants plus a conservative fallback for anything else.

Sources (checked 2026-04; prices may have drifted since):

* OpenRouter: https://openrouter.ai/models
* DeepSeek:   https://platform.deepseek.com/api-docs/pricing
* OpenAI:     https://openai.com/api/pricing

If a model doesn't match, ``lookup_price`` falls back to a provider-level
average so the dashboard still shows *something* sensible rather than $0.
"""

from __future__ import annotations

# Each entry: (prompt_per_1m, completion_per_1m) in USD.
# Both values must be non-negative floats.
_MODEL_PRICES: dict[str, tuple[float, float]] = {
    # ---- OpenRouter (prefix `vendor/model`; prices mirror upstream) ----
    "openai/gpt-4o": (5.00, 15.00),
    "openai/gpt-4o-mini": (0.15, 0.60),
    "anthropic/claude-3.5-sonnet": (3.00, 15.00),
    "anthropic/claude-3.5-haiku": (0.80, 4.00),
    "google/gemini-2.0-flash-001": (0.10, 0.40),
    "meta-llama/llama-3.1-70b-instruct": (0.52, 0.75),
    # ---- DeepSeek (direct) ----
    "deepseek-chat": (0.27, 1.10),
    "deepseek-reasoner": (0.55, 2.19),
    # ---- OpenAI (direct) ----
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1-mini": (0.40, 1.60),
    "o1-mini": (3.00, 12.00),
}

# Provider-level fallbacks when we can't match a specific model id.
# Picked to be "reasonable mid-tier" for each gateway.
_PROVIDER_FALLBACK: dict[str, tuple[float, float]] = {
    "openrouter": (1.00, 4.00),
    "deepseek": (0.27, 1.10),
    "openai": (1.00, 4.00),
}

# Last-resort default — used when we have no hint at all.
_DEFAULT_FALLBACK: tuple[float, float] = (1.00, 4.00)


def lookup_price(model_id: str | None, provider: str | None) -> tuple[float, float]:
    """Return ``(prompt_per_1m, completion_per_1m)`` in USD.

    Never raises — unknown models get a provider-level or global
    fallback so the dashboard always shows a finite dollar figure.
    """
    if model_id and model_id in _MODEL_PRICES:
        return _MODEL_PRICES[model_id]
    if provider and provider in _PROVIDER_FALLBACK:
        return _PROVIDER_FALLBACK[provider]
    return _DEFAULT_FALLBACK


def estimate_cost(
    prompt_tokens: int | None,
    completion_tokens: int | None,
    model_id: str | None,
    provider: str | None,
) -> float:
    """Estimate USD cost for a single turn. Missing counts → 0 contribution."""
    prompt_price, completion_price = lookup_price(model_id, provider)
    pt = prompt_tokens or 0
    ct = completion_tokens or 0
    return (pt / 1_000_000.0) * prompt_price + (ct / 1_000_000.0) * completion_price


__all__ = ["estimate_cost", "lookup_price"]
