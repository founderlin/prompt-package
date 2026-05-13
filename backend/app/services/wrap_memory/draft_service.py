"""Wrap draft service — the public entry point for Phase 2.

Single function: :func:`create_wrap_draft`. Takes a normalized
:class:`WrapRequest`, routes through the right provider, and returns
a clean :class:`WrapAnalysisResult` (the "draft").

The draft is *not yet persisted*. Phase 3 will plug this output into
the Markdown writer (already shipped in Phase 1) and a route handler
that decides whether to save automatically (Quick/Advanced) or wait
for user review (Routine).

Why a thin wrapper around ``provider.generate_wrap_analysis``?

* It's the single seam where future cross-cutting concerns slot in
  (usage tracking, telemetry, rate limiting, retries) without
  touching providers.
* It lets routes call a stable, well-named function rather than
  poking at the provider interface directly.
* Normalization (defensive fill-in of empty fields, tag dedupe) lives
  here so every provider — mock or real — produces UI-safe results.
"""

from __future__ import annotations

from typing import Any

from .providers import (
    LLMCallable,
    WrapProvider,
    WrapProviderError,
    get_wrap_provider,
)
from .types import WrapAnalysisResult, WrapRequest


def create_wrap_draft(
    request: WrapRequest,
    *,
    provider: WrapProvider | None = None,
    allow_network: bool = False,
    api_key: str | None = None,
    llm_caller: LLMCallable | None = None,
    user: Any = None,
) -> WrapAnalysisResult:
    """Generate a wrap draft for ``request``.

    Provider resolution order:
    * If ``provider`` is supplied, use it as-is. Tests rely on this
      branch to inject a captured mock.
    * Otherwise delegate to :func:`get_wrap_provider`, which picks
      between real LLM and mock based on ``allow_network`` + key
      availability.

    Returns a normalized :class:`WrapAnalysisResult`. Raises
    :class:`WrapProviderError` on hard failures (no fallback at this
    layer — the route handler decides whether to surface the error or
    retry with the mock provider).
    """
    if provider is None:
        provider = get_wrap_provider(
            request.model,
            api_key=api_key,
            allow_network=allow_network,
            llm_caller=llm_caller,
            user=user,
        )

    result = provider.generate_wrap_analysis(request)
    return _normalize_result(result, request)


def _normalize_result(
    result: WrapAnalysisResult, request: WrapRequest
) -> WrapAnalysisResult:
    """Fill in missing defaults and dedupe tags / lists.

    Catches the rare cases where a provider produces a *parseable* but
    semantically empty result (no title, empty markdown). Frontend
    code can then treat the result as always-renderable.
    """
    title = result.title.strip() if result.title else ""
    if not title:
        title = request.project_name + " Wrap"

    # Tags: lowercase, trimmed, deduped, max 8.
    seen: set[str] = set()
    deduped_tags: list[str] = []
    for tag in result.tags or []:
        cleaned = tag.strip().lower()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        deduped_tags.append(cleaned)
        if len(deduped_tags) >= 8:
            break

    return WrapAnalysisResult(
        title=title,
        topic=result.topic or request.project_name,
        topic_drift=bool(result.topic_drift),
        should_split=bool(result.should_split),
        split_suggestions=list(result.split_suggestions or []),
        summary=result.summary,
        key_decisions=list(result.key_decisions or []),
        requirements=list(result.requirements or []),
        todos=list(result.todos or []),
        risks=list(result.risks) if result.risks else None,
        filtering_summary=result.filtering_summary,
        tags=deduped_tags,
        markdown=result.markdown,
    )


__all__ = ["create_wrap_draft", "WrapProviderError"]
