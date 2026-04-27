"""Provider-agnostic LLM HTTP client.

Replaces R3's ``openrouter_service`` as the canonical entry point in R14.
The legacy module re-exports from here, so existing imports of
``OpenRouterError`` / ``OpenRouterKeyInfo`` / ``chat_completion`` /
``verify_api_key`` keep working unchanged.

All three currently-supported providers (OpenRouter, DeepSeek, OpenAI)
speak OpenAI-compatible chat completions, so the call shape barely
changes between them — we just swap the base URL and (for OpenRouter)
the verify endpoint.

Side-effect free: callers pass an API key + provider id in. We never
log the key.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

import requests
from flask import current_app

from app.providers import DEFAULT_PROVIDER, ProviderConfig, get_provider


# ---------- Errors & data shapes -------------------------------------------------


class LLMError(Exception):
    """Wraps any failure when talking to an upstream LLM gateway."""

    def __init__(
        self,
        message: str,
        *,
        status: int = 502,
        code: str = "llm_error",
        provider: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.provider = provider


# Back-compat alias: chat_service / settings_service / smoke tests still
# reference ``OpenRouterError``. Keep them as type aliases of LLMError so
# existing ``except`` blocks keep working.
class OpenRouterError(LLMError):
    pass


@dataclass
class KeyInfo:
    """Optional metadata returned by a provider's verify endpoint.

    OpenRouter populates everything; DeepSeek / OpenAI only confirm "the
    key works" via /models, so they leave most fields ``None``.
    """

    label: Optional[str] = None
    usage: Optional[float] = None
    limit: Optional[float] = None
    limit_remaining: Optional[float] = None
    is_free_tier: Optional[bool] = None
    model_count: Optional[int] = None  # deepseek/openai populate this from /models

    @classmethod
    def from_openrouter(cls, payload: dict) -> "KeyInfo":
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            data = {}
        return cls(
            label=data.get("label"),
            usage=data.get("usage"),
            limit=data.get("limit"),
            limit_remaining=data.get("limit_remaining"),
            is_free_tier=data.get("is_free_tier"),
        )

    @classmethod
    def from_models_list(cls, payload: dict) -> "KeyInfo":
        data = payload.get("data") if isinstance(payload, dict) else None
        count = len(data) if isinstance(data, list) else None
        return cls(model_count=count)

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "usage": self.usage,
            "limit": self.limit,
            "limit_remaining": self.limit_remaining,
            "is_free_tier": self.is_free_tier,
            "model_count": self.model_count,
        }


# Legacy alias retained for back-compat.
OpenRouterKeyInfo = KeyInfo


@dataclass
class ChatCompletion:
    content: str
    model: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    finish_reason: str | None
    raw_id: str | None
    provider: str | None = None

    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "finish_reason": self.finish_reason,
            "id": self.raw_id,
            "provider": self.provider,
        }


# ---------- HTTP helpers ---------------------------------------------------------


def _user_agent() -> str:
    version = current_app.config.get("APP_VERSION", "0.0.0")
    return f"imrockey/{version}"


def _verify_timeout() -> float:
    return float(current_app.config.get("LLM_VERIFY_TIMEOUT_SECONDS", 10))


def _chat_timeout() -> float:
    raw = current_app.config.get("OPENROUTER_CHAT_TIMEOUT_SECONDS")
    if raw:
        return float(raw)
    return float(current_app.config.get("OPENROUTER_TIMEOUT_SECONDS", 10)) * 6


def _auth_headers(api_key: str, cfg: ProviderConfig) -> dict[str, str]:
    headers: dict[str, str] = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Accept": "application/json",
        "User-Agent": _user_agent(),
    }
    headers.update(cfg.extra_headers)
    return headers


# ---------- Verify ---------------------------------------------------------------


def verify_api_key(api_key: str, *, provider: str | None = None) -> KeyInfo:
    """Validate ``api_key`` against ``provider`` and return any metadata.

    Raises :class:`LLMError` when the key is rejected or the request fails.
    Backwards compatible: when called with a single positional argument
    we default to OpenRouter (matches R3's signature).
    """
    if not api_key or not api_key.strip():
        raise LLMError(
            "API key is empty.",
            status=400,
            code="invalid_api_key",
            provider=provider,
        )

    provider_id = provider or DEFAULT_PROVIDER
    cfg = get_provider(provider_id)

    url = f"{cfg.base_url()}{cfg.verify_path}"
    headers = _auth_headers(api_key, cfg)

    try:
        response = requests.get(url, headers=headers, timeout=_verify_timeout())
    except requests.Timeout as exc:
        raise LLMError(
            f"{cfg.label} request timed out.",
            status=504,
            code="llm_timeout",
            provider=cfg.id,
        ) from exc
    except requests.RequestException as exc:
        raise LLMError(
            f"Could not reach {cfg.label}.",
            status=502,
            code="llm_unreachable",
            provider=cfg.id,
        ) from exc

    if response.status_code == 401:
        raise LLMError(
            f"{cfg.label} rejected this API key.",
            status=401,
            code="invalid_api_key",
            provider=cfg.id,
        )
    if response.status_code == 403:
        raise LLMError(
            f"This {cfg.label} key is not allowed to access {cfg.verify_path}.",
            status=403,
            code="forbidden_api_key",
            provider=cfg.id,
        )
    if response.status_code >= 400:
        raise LLMError(
            f"{cfg.label} returned HTTP {response.status_code}.",
            status=502,
            code="llm_error",
            provider=cfg.id,
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise LLMError(
            f"{cfg.label} response was not valid JSON.",
            status=502,
            code="llm_bad_response",
            provider=cfg.id,
        ) from exc

    if cfg.id == "openrouter":
        return KeyInfo.from_openrouter(payload)
    return KeyInfo.from_models_list(payload)


# ---------- Chat completions -----------------------------------------------------


def chat_completion(
    api_key: str,
    *,
    model: str,
    messages: Iterable[dict],
    provider: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    extra: dict | None = None,
) -> ChatCompletion:
    """Call the provider's ``/chat/completions`` endpoint and parse choice 0.

    ``provider`` defaults to ``openrouter`` for back-compat with R3 callers.
    """
    if not api_key or not api_key.strip():
        raise LLMError("API key is empty.", status=400, code="invalid_api_key", provider=provider)
    if not model or not model.strip():
        raise LLMError("Model is required.", status=400, code="model_required", provider=provider)

    provider_id = provider or DEFAULT_PROVIDER
    cfg = get_provider(provider_id)

    body: dict = {
        "model": model.strip(),
        "messages": list(messages),
    }
    if temperature is not None:
        body["temperature"] = float(temperature)
    if max_tokens is not None:
        body["max_tokens"] = int(max_tokens)
    if extra:
        body.update(extra)

    headers = _auth_headers(api_key, cfg)
    headers["Content-Type"] = "application/json"

    url = f"{cfg.base_url()}/chat/completions"

    try:
        response = requests.post(url, headers=headers, json=body, timeout=_chat_timeout())
    except requests.Timeout as exc:
        raise LLMError(
            f"{cfg.label} chat request timed out.",
            status=504,
            code="llm_timeout",
            provider=cfg.id,
        ) from exc
    except requests.RequestException as exc:
        raise LLMError(
            f"Could not reach {cfg.label}.",
            status=502,
            code="llm_unreachable",
            provider=cfg.id,
        ) from exc

    if response.status_code == 401:
        raise LLMError(
            f"{cfg.label} rejected your API key. Re-add it in Settings.",
            status=401,
            code="invalid_api_key",
            provider=cfg.id,
        )
    if response.status_code == 402:
        raise LLMError(
            f"{cfg.label} says this key has insufficient credits.",
            status=402,
            code="insufficient_credits",
            provider=cfg.id,
        )
    if response.status_code == 404:
        raise LLMError(
            f"{cfg.label} does not recognize that model.",
            status=400,
            code="model_not_found",
            provider=cfg.id,
        )
    if response.status_code == 429:
        raise LLMError(
            f"{cfg.label} rate-limited this request. Try again shortly.",
            status=429,
            code="rate_limited",
            provider=cfg.id,
        )

    if response.status_code >= 400:
        message = f"{cfg.label} returned HTTP {response.status_code}."
        try:
            payload = response.json()
            err = payload.get("error") if isinstance(payload, dict) else None
            if isinstance(err, dict) and err.get("message"):
                message = err["message"]
        except ValueError:
            pass
        raise LLMError(message, status=502, code="llm_error", provider=cfg.id)

    try:
        payload = response.json()
    except ValueError as exc:
        raise LLMError(
            f"{cfg.label} response was not valid JSON.",
            status=502,
            code="llm_bad_response",
            provider=cfg.id,
        ) from exc

    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, list) or not choices:
        raise LLMError(
            f"{cfg.label} returned no completion choices.",
            status=502,
            code="llm_empty_choice",
            provider=cfg.id,
        )

    first = choices[0] or {}
    msg = first.get("message") if isinstance(first, dict) else None
    content = ""
    if isinstance(msg, dict):
        raw_content = msg.get("content")
        if isinstance(raw_content, str):
            content = raw_content
        elif isinstance(raw_content, list):
            parts = []
            for part in raw_content:
                if isinstance(part, dict) and part.get("type") == "text":
                    parts.append(str(part.get("text", "")))
                elif isinstance(part, str):
                    parts.append(part)
            content = "".join(parts)

    if not content.strip():
        raise LLMError(
            f"{cfg.label} returned an empty response.",
            status=502,
            code="llm_empty_content",
            provider=cfg.id,
        )

    usage = payload.get("usage") if isinstance(payload, dict) else None
    if not isinstance(usage, dict):
        usage = {}

    return ChatCompletion(
        content=content,
        model=payload.get("model") if isinstance(payload, dict) else None,
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
        total_tokens=usage.get("total_tokens"),
        finish_reason=first.get("finish_reason") if isinstance(first, dict) else None,
        raw_id=payload.get("id") if isinstance(payload, dict) else None,
        provider=cfg.id,
    )


__all__ = [
    "ChatCompletion",
    "KeyInfo",
    "LLMError",
    "OpenRouterError",
    "OpenRouterKeyInfo",
    "chat_completion",
    "verify_api_key",
]
