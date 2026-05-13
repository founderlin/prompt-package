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
import json
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
    return f"promptpackage/{version}"


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


def chat_completion_stream(
    api_key: str,
    *,
    model: str,
    messages: Iterable[dict],
    provider: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    extra: dict | None = None,
):
    """Stream ``/chat/completions`` deltas as ``(kind, value)`` tuples.

    Yields tuples in chronological order:

    * ``("delta", "text fragment")`` — incremental assistant content.
    * ``("done", ChatCompletion)`` — terminal event with the assembled
      content + usage metadata (best-effort; some providers omit
      ``usage`` in streaming mode).

    Raises :class:`LLMError` for the same conditions as
    :func:`chat_completion`. Network errors mid-stream raise so the
    caller can surface a partial completion + error event.

    All three providers we ship (OpenAI / DeepSeek / OpenRouter) use
    the OpenAI-compatible SSE shape:

        data: {"choices":[{"delta":{"content":"…"}}]}
        ...
        data: [DONE]

    so a single parser handles the full catalog.
    """
    if not api_key or not api_key.strip():
        raise LLMError(
            "API key is empty.", status=400, code="invalid_api_key", provider=provider
        )
    if not model or not model.strip():
        raise LLMError(
            "Model is required.", status=400, code="model_required", provider=provider
        )

    provider_id = provider or DEFAULT_PROVIDER
    cfg = get_provider(provider_id)

    body: dict = {
        "model": model.strip(),
        "messages": list(messages),
        "stream": True,
    }
    if temperature is not None:
        body["temperature"] = float(temperature)
    if max_tokens is not None:
        body["max_tokens"] = int(max_tokens)
    if extra:
        body.update(extra)

    headers = _auth_headers(api_key, cfg)
    headers["Content-Type"] = "application/json"
    headers["Accept"] = "text/event-stream"

    url = f"{cfg.base_url()}/chat/completions"

    try:
        response = requests.post(
            url, headers=headers, json=body, timeout=_chat_timeout(), stream=True
        )
    except requests.Timeout as exc:
        raise LLMError(
            f"{cfg.label} chat request timed out.",
            status=504, code="llm_timeout", provider=cfg.id,
        ) from exc
    except requests.RequestException as exc:
        raise LLMError(
            f"Could not reach {cfg.label}.",
            status=502, code="llm_unreachable", provider=cfg.id,
        ) from exc

    if response.status_code == 401:
        raise LLMError(
            f"{cfg.label} rejected your API key. Re-add it in Settings.",
            status=401, code="invalid_api_key", provider=cfg.id,
        )
    if response.status_code == 402:
        raise LLMError(
            f"{cfg.label} says this key has insufficient credits.",
            status=402, code="insufficient_credits", provider=cfg.id,
        )
    if response.status_code == 404:
        raise LLMError(
            f"{cfg.label} does not recognize that model.",
            status=400, code="model_not_found", provider=cfg.id,
        )
    if response.status_code == 429:
        raise LLMError(
            f"{cfg.label} rate-limited this request. Try again shortly.",
            status=429, code="rate_limited", provider=cfg.id,
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

    parts: list[str] = []
    model_id: str | None = None
    raw_id: str | None = None
    finish_reason: str | None = None
    usage: dict = {}

    # IMPORTANT: do not use ``response.iter_lines(decode_unicode=True)``.
    #
    # That helper hands each raw byte chunk to ``str.decode('utf-8')``
    # *per chunk*, without remembering trailing partial code points. If
    # the upstream LLM emits a 3-byte CJK character whose bytes happen
    # to straddle a TCP chunk boundary, the second chunk starts mid-
    # codepoint and decodes to mojibake (e.g. "你好" → "ä½ å¥½").
    #
    # We work at the byte level here, accumulate a buffer, split lines
    # on ``\n``, and only decode *whole lines* — which always end on a
    # UTF-8 codepoint boundary because the line terminator itself is
    # ASCII.
    byte_buffer = b""

    def _iter_lines():
        nonlocal byte_buffer
        for chunk in response.iter_content(chunk_size=None, decode_unicode=False):
            if not chunk:
                continue
            byte_buffer += chunk
            while b"\n" in byte_buffer:
                line_bytes, byte_buffer = byte_buffer.split(b"\n", 1)
                if line_bytes.endswith(b"\r"):
                    line_bytes = line_bytes[:-1]
                try:
                    yield line_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    # Last-resort fallback: replace invalid sequences
                    # rather than abort the whole stream. Should not
                    # happen given the per-line decoding above, but
                    # better a few "?" than a crashed completion.
                    yield line_bytes.decode("utf-8", errors="replace")
        # Flush any trailing line that wasn't \n-terminated.
        if byte_buffer:
            try:
                yield byte_buffer.decode("utf-8")
            except UnicodeDecodeError:
                yield byte_buffer.decode("utf-8", errors="replace")
            byte_buffer = b""

    try:
        for raw_line in _iter_lines():
            if not raw_line:
                continue
            # Some providers prefix comments with ``:`` — ignore those.
            if raw_line.startswith(":"):
                continue
            if not raw_line.startswith("data:"):
                continue
            data = raw_line[5:].strip()
            if data == "[DONE]":
                break
            try:
                event = json.loads(data)
            except (ValueError, TypeError):
                continue

            if not isinstance(event, dict):
                continue
            if model_id is None and isinstance(event.get("model"), str):
                model_id = event["model"]
            if raw_id is None and isinstance(event.get("id"), str):
                raw_id = event["id"]

            choices = event.get("choices")
            if not isinstance(choices, list) or not choices:
                # Some providers send a final ``usage`` event with no choices.
                ev_usage = event.get("usage")
                if isinstance(ev_usage, dict):
                    usage = ev_usage
                continue

            choice0 = choices[0] or {}
            delta = choice0.get("delta") if isinstance(choice0, dict) else None
            if isinstance(delta, dict):
                content_chunk = delta.get("content")
                if isinstance(content_chunk, str) and content_chunk:
                    parts.append(content_chunk)
                    yield ("delta", content_chunk)
            fr = choice0.get("finish_reason") if isinstance(choice0, dict) else None
            if isinstance(fr, str):
                finish_reason = fr
            ev_usage = event.get("usage")
            if isinstance(ev_usage, dict):
                usage = ev_usage
    finally:
        try:
            response.close()
        except Exception:  # pragma: no cover - defensive
            pass

    content = "".join(parts)
    if not content.strip():
        # Mirror chat_completion's behavior — an empty stream is still
        # an upstream failure even if the HTTP status was 200.
        raise LLMError(
            f"{cfg.label} returned an empty response.",
            status=502, code="llm_empty_content", provider=cfg.id,
        )

    completion = ChatCompletion(
        content=content,
        model=model_id,
        prompt_tokens=usage.get("prompt_tokens") if isinstance(usage, dict) else None,
        completion_tokens=usage.get("completion_tokens") if isinstance(usage, dict) else None,
        total_tokens=usage.get("total_tokens") if isinstance(usage, dict) else None,
        finish_reason=finish_reason,
        raw_id=raw_id,
        provider=cfg.id,
    )
    yield ("done", completion)


__all__ = [
    "ChatCompletion",
    "KeyInfo",
    "LLMError",
    "OpenRouterError",
    "OpenRouterKeyInfo",
    "chat_completion",
    "chat_completion_stream",
    "verify_api_key",
]
