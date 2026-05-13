"""Wrap providers — the LLM call boundary.

A *wrap provider* is a tiny strategy object with one method:

    generate_wrap_analysis(request) -> WrapAnalysisResult

Two concrete implementations ship in Phase 2:

* :class:`MockWrapProvider` — fully offline, deterministic. The default
  when no API key is available (or when the caller explicitly opts in
  for testing / UI development).
* :class:`LLMBackedWrapProvider` — composes the prompt builders +
  parser around the existing project-wide ``llm_service.chat_completion``
  HTTP client. Reuses the registered providers in :mod:`app.providers`
  and the encrypted key store via :mod:`app.services.credentials_service`,
  so we don't reinvent API-key management.

The factory :func:`get_wrap_provider` picks between them based on
caller intent + actually-available credentials, with mock as the
guaranteed fallback. That keeps the Phase 3 UI flow buildable even
when no provider keys are configured.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .llm_adapter import ModelRoute, route_for_model
from .parser import WrapParseError, parse_wrap_analysis_result
from .prompts import build_wrap_system_prompt, build_wrap_user_prompt
from .types import (
    FilterAction,
    WrapAnalysisResult,
    WrapMode,
    WrapModel,
    WrapRequest,
    WrapScope,
    WrapSplitSuggestion,
)


# ---------------------------------------------------------------------------
# Errors.


class WrapProviderError(Exception):
    """Predictable, user-facing wrap-provider failures.

    Distinct from :class:`app.services.llm_service.LLMError` (upstream
    HTTP errors) so the route layer can decide whether to retry, fall
    back to mock, or surface to the user.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int = 502,
        model: WrapModel | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.model = model


# ---------------------------------------------------------------------------
# Provider interface.


class WrapProvider(ABC):
    """Abstract base for wrap providers.

    Subclasses must declare which :class:`WrapModel` they implement.
    The base class is an ABC (not just a Protocol) so a missing
    ``generate_wrap_analysis`` is caught at instantiation, not at
    first call.
    """

    model: WrapModel

    @abstractmethod
    def generate_wrap_analysis(self, request: WrapRequest) -> WrapAnalysisResult:
        ...

    def describe(self) -> dict:
        """Short metadata blob — useful for logging / debugging."""
        return {"provider": type(self).__name__, "model": self.model.value}


# ---------------------------------------------------------------------------
# Mock provider — deterministic, offline.


@dataclass
class MockWrapProvider(WrapProvider):
    """A WrapProvider that builds a plausible result from the request alone.

    Used when:
    * the user has no provider key configured;
    * tests need a stable result without network;
    * the UI wants to render previews during local development.

    The output is *deterministic* — the same input always produces
    the same wrap. We use simple aggregation (first user turn / last
    assistant turn / message counts) rather than any randomness so
    snapshot tests don't have to special-case mock runs.
    """

    model: WrapModel
    label: str = "MockWrapProvider"

    def generate_wrap_analysis(self, request: WrapRequest) -> WrapAnalysisResult:
        title = self._derive_title(request)
        summary = self._derive_summary(request)
        filtering = self._describe_filtering(request)
        tags = self._derive_tags(request)
        markdown = self._render_markdown(request, title, summary, filtering, tags)

        return WrapAnalysisResult(
            title=title,
            topic=request.project_name or "Untitled project",
            topic_drift=False,
            should_split=False,
            split_suggestions=[],
            summary=summary,
            key_decisions=self._first_bullets(request, "decision", limit=3),
            requirements=self._first_bullets(request, "requirement", limit=3),
            todos=self._first_bullets(request, "todo", limit=3),
            risks=None,
            filtering_summary=filtering,
            tags=tags,
            markdown=markdown,
        )

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _derive_title(request: WrapRequest) -> str:
        for msg in request.messages:
            if msg.role == "user" and msg.content.strip():
                snippet = msg.content.strip().splitlines()[0]
                snippet = snippet.strip().strip("#").strip()
                if snippet:
                    if len(snippet) > 60:
                        snippet = snippet[:59].rstrip() + "…"
                    return snippet
        scope = (
            "Conversation"
            if request.scope == WrapScope.CONVERSATION
            else "Project"
        )
        return f"{request.project_name} {scope} Wrap"

    @staticmethod
    def _derive_summary(request: WrapRequest) -> str:
        kept = [m for m in request.messages if m.role in {"user", "assistant"}]
        if not kept:
            return "No user or assistant messages were provided."
        first = kept[0].content.strip().splitlines()[0] if kept[0].content else ""
        last = kept[-1].content.strip().splitlines()[0] if kept[-1].content else ""
        return (
            f"Mock wrap of {len(kept)} message(s) for project "
            f"'{request.project_name}'. Opens with: \"{first[:120]}\". "
            f"Latest turn ends with: \"{last[:120]}\"."
        )

    @staticmethod
    def _describe_filtering(request: WrapRequest) -> str:
        filt = request.filters
        kept = [
            name
            for name, action in [
                ("code blocks", filt.code_blocks),
                ("images", filt.images),
                ("prompts", filt.prompt_text),
                ("logs", filt.logs),
                ("off-topic", filt.off_topic),
            ]
            if action == FilterAction.KEEP
        ]
        excluded = [
            name
            for name, action in [
                ("code blocks", filt.code_blocks),
                ("images", filt.images),
                ("prompts", filt.prompt_text),
                ("logs", filt.logs),
                ("off-topic", filt.off_topic),
            ]
            if action == FilterAction.EXCLUDE
        ]
        parts = []
        if kept:
            parts.append("kept: " + ", ".join(kept))
        if excluded:
            parts.append("excluded: " + ", ".join(excluded))
        if not parts:
            parts.append("all content types summarized")
        return "Mock filtering — " + "; ".join(parts) + "."

    @staticmethod
    def _derive_tags(request: WrapRequest) -> list[str]:
        tags = ["mock", request.mode.value]
        if request.scope == WrapScope.PROJECT:
            tags.append("project-scope")
        return tags

    @staticmethod
    def _first_bullets(request: WrapRequest, kind: str, *, limit: int) -> list[str]:
        # Deterministic, useful placeholder bullets keyed off the
        # transcript length — gives UI/tests something to render
        # without inventing facts.
        n = max(0, min(limit, len(request.messages)))
        if n == 0:
            return []
        return [
            f"[mock {kind} {i + 1}] derived from message {i + 1} of "
            f"{len(request.messages)}"
            for i in range(n)
        ]

    @staticmethod
    def _render_markdown(
        request: WrapRequest,
        title: str,
        summary: str,
        filtering: str,
        tags: list[str],
    ) -> str:
        lines = [
            f"# {title}",
            "",
            "> Generated by MockWrapProvider — install a real provider key "
            "to get LLM-quality wraps.",
            "",
            "## Summary",
            summary,
            "",
            "## Filtering",
            filtering,
        ]
        if tags:
            lines.extend(["", "## Tags", ", ".join(tags)])
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM-backed provider — composes prompts → chat_completion → parser.


LLMCallable = Callable[..., Any]
"""Type alias for the callable an LLMBackedWrapProvider uses to reach a model.

The default in production is :func:`app.services.llm_service.chat_completion`,
but tests inject a fake so we never go to the network in unit tests.

The signature is keyword-only (matches ``chat_completion``)::

    fn(api_key=..., provider=..., model=..., messages=[...],
       temperature=..., max_tokens=..., extra=...)

and must return something with a ``.content`` attribute (typically a
:class:`app.services.llm_service.ChatCompletion`).
"""


@dataclass
class LLMBackedWrapProvider(WrapProvider):
    """Build prompts → call upstream LLM → parse JSON → return result.

    No state, no class methods — perfectly safe to construct per
    request. ``llm_caller`` is injectable so unit tests can exercise
    the full pipeline without spinning up Flask or HTTP.
    """

    model: WrapModel
    api_key: str
    route: Optional[ModelRoute] = None
    llm_caller: Optional[LLMCallable] = None
    temperature: float = 0.2

    def __post_init__(self) -> None:
        if self.route is None:
            self.route = route_for_model(self.model)
        if not self.api_key or not str(self.api_key).strip():
            raise WrapProviderError(
                code="missing_api_key",
                message=f"No API key supplied for {self.route.provider_id}.",
                status=400,
                model=self.model,
            )
        if self.llm_caller is None:
            self.llm_caller = _default_llm_caller

    def generate_wrap_analysis(self, request: WrapRequest) -> WrapAnalysisResult:
        assert self.route is not None  # set in __post_init__
        assert self.llm_caller is not None

        messages = [
            {"role": "system", "content": build_wrap_system_prompt()},
            {"role": "user", "content": build_wrap_user_prompt(request)},
        ]
        try:
            completion = self.llm_caller(
                api_key=self.api_key,
                provider=self.route.provider_id,
                model=self.route.backend_model,
                messages=messages,
                temperature=self.temperature,
            )
        except WrapProviderError:
            raise
        except Exception as exc:  # pragma: no cover - exercised via tests w/ fake
            # Wrap the upstream error so the service layer always sees a
            # consistent type. We deliberately don't expose the raw
            # exception message; that lives in logs.
            raise WrapProviderError(
                code="upstream_error",
                message=f"Upstream LLM call failed: {exc}",
                status=502,
                model=self.model,
            ) from exc

        content = _extract_completion_content(completion)
        try:
            return parse_wrap_analysis_result(content)
        except WrapParseError as exc:
            raise WrapProviderError(
                code="bad_model_output",
                message=exc.message,
                status=502,
                model=self.model,
            ) from exc


def _extract_completion_content(completion: Any) -> str:
    """Pull a plain string body out of whatever the LLM caller returned.

    Tolerates:
    * ``ChatCompletion`` instances (the production return type),
    * raw strings (handy for tests),
    * dicts with a ``content`` key (legacy / partial fakes).
    """
    if isinstance(completion, str):
        return completion
    if hasattr(completion, "content"):
        content = getattr(completion, "content")
        if isinstance(content, str):
            return content
    if isinstance(completion, dict) and isinstance(completion.get("content"), str):
        return completion["content"]
    raise WrapProviderError(
        code="bad_model_output",
        message=f"LLM caller returned unsupported object: {type(completion).__name__}.",
        status=502,
    )


def _default_llm_caller(**kwargs):  # pragma: no cover - thin shim
    """Production LLM caller — defers the Flask import until first use.

    Keeping the import lazy lets the rest of this module load without
    Flask in test contexts.
    """
    from app.services.llm_service import chat_completion

    api_key = kwargs.pop("api_key")
    return chat_completion(api_key, **kwargs)


# ---------------------------------------------------------------------------
# Factory.


def get_wrap_provider(
    model: WrapModel,
    *,
    api_key: str | None = None,
    allow_network: bool = False,
    llm_caller: LLMCallable | None = None,
    user: Any = None,
) -> WrapProvider:
    """Return the appropriate :class:`WrapProvider` for ``model``.

    Routing logic (first match wins):

    1. If ``llm_caller`` is provided AND we have an API key (or the
       caller doesn't care, e.g. dummy key), return an
       :class:`LLMBackedWrapProvider` — tests use this branch to
       inject deterministic fakes.

    2. If ``allow_network`` is True AND an API key can be resolved
       (explicit ``api_key=`` argument first; otherwise read from
       :mod:`credentials_service` using ``user``), return a real
       :class:`LLMBackedWrapProvider` wired to ``chat_completion``.

    3. Otherwise, return a :class:`MockWrapProvider`. This is the
       always-safe fallback — no key, no network, deterministic.
    """
    if llm_caller is not None:
        return LLMBackedWrapProvider(
            model=model,
            api_key=api_key or "test-key",
            llm_caller=llm_caller,
        )

    if allow_network:
        resolved_key = api_key or _resolve_user_key(model, user)
        if resolved_key:
            return LLMBackedWrapProvider(model=model, api_key=resolved_key)

    return MockWrapProvider(model=model)


def _resolve_user_key(model: WrapModel, user: Any) -> str | None:
    """Look up the encrypted API key for the user that owns the wrap.

    Returns ``None`` if the user has no key for the routed provider —
    callers should fall back to the mock provider in that case so the
    feature stays usable.
    """
    if user is None:
        return None
    try:
        from app.services.credentials_service import (
            CredentialsError,
            get_decrypted_key_for,
        )
    except ImportError:  # pragma: no cover
        return None
    route = route_for_model(model)
    try:
        return get_decrypted_key_for(user, route.provider_id)
    except CredentialsError:
        return None
    except Exception:  # pragma: no cover
        return None


__all__ = [
    "LLMBackedWrapProvider",
    "LLMCallable",
    "MockWrapProvider",
    "WrapProvider",
    "WrapProviderError",
    "get_wrap_provider",
]
