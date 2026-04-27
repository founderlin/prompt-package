"""Legacy OpenRouter-only entry point.

R14 generalized this into :mod:`app.services.llm_service`. We keep the
old import surface (``OpenRouterError`` / ``OpenRouterKeyInfo`` /
``chat_completion`` / ``verify_api_key`` / ``ChatCompletion``) so the
rest of the codebase and any external tooling pinned to R3 names keep
working unchanged. New code should import from ``llm_service``.

Behaviour-wise this module is a thin compatibility veneer — both
``chat_completion`` and ``verify_api_key`` default to
``provider='openrouter'``.
"""

from __future__ import annotations

from typing import Iterable

from app.services.llm_service import (
    ChatCompletion,
    KeyInfo as _KeyInfo,
    LLMError,
    OpenRouterError,
    OpenRouterKeyInfo,
    chat_completion as _chat_completion,
    verify_api_key as _verify_api_key,
)


def verify_api_key(api_key: str) -> _KeyInfo:
    return _verify_api_key(api_key, provider="openrouter")


def chat_completion(
    api_key: str,
    *,
    model: str,
    messages: Iterable[dict],
    temperature: float | None = None,
    max_tokens: int | None = None,
    extra: dict | None = None,
) -> ChatCompletion:
    return _chat_completion(
        api_key,
        model=model,
        messages=messages,
        provider="openrouter",
        temperature=temperature,
        max_tokens=max_tokens,
        extra=extra,
    )


__all__ = [
    "ChatCompletion",
    "LLMError",
    "OpenRouterError",
    "OpenRouterKeyInfo",
    "chat_completion",
    "verify_api_key",
]
