"""Route :class:`WrapModel` enum values to real provider+model ids.

``WrapModel`` is intentionally a **product-facing** catalog
(``deepseek-v4-flash`` / ``gemini-3.1-flash`` / ``gpt-5.4-nano``) so
the UI never has to know which backend gateway answers a wrap.

This module is the single place that turns those product names into
concrete (provider_id, backend_model) pairs the existing
``llm_service.chat_completion()`` understands.

When a real model name in the product catalog drifts (e.g. DeepSeek
releases ``deepseek-v5-flash``), only this table needs to change —
everything downstream keeps working.
"""

from __future__ import annotations

from dataclasses import dataclass

from .types import WrapModel


@dataclass(frozen=True)
class ModelRoute:
    """One row of the WrapModel routing table.

    ``provider_id`` is one of the ids registered in
    :mod:`app.providers` (``openrouter`` / ``deepseek`` / ``openai``).
    ``backend_model`` is the exact string the gateway expects in its
    ``/chat/completions`` payload.
    """

    wrap_model: WrapModel
    provider_id: str
    backend_model: str

    def to_dict(self) -> dict:
        return {
            "wrapModel": self.wrap_model.value,
            "providerId": self.provider_id,
            "backendModel": self.backend_model,
        }


# Routing decisions:
#
# * deepseek-v4-flash → direct DeepSeek (``deepseek-chat`` is the
#   current fast/general model in their catalog; swap to
#   ``deepseek-v4-flash`` verbatim when it actually ships).
# * gemini-3.1-flash → OpenRouter is the only way we reach Google
#   models without a separate Vertex integration, and OR exposes a
#   fast Gemini Flash variant.
# * gpt-5.4-nano → direct OpenAI, mapped to GPT-4o mini as the
#   cheapest/fastest available stand-in until 5.4-nano lands.
#
# These are *occlusion-tolerant* mappings: a future migration that
# renames either side only touches this dict.
MODEL_ROUTES: dict[WrapModel, ModelRoute] = {
    WrapModel.DEEPSEEK_V4_FLASH: ModelRoute(
        wrap_model=WrapModel.DEEPSEEK_V4_FLASH,
        provider_id="deepseek",
        backend_model="deepseek-chat",
    ),
    WrapModel.GEMINI_31_FLASH: ModelRoute(
        wrap_model=WrapModel.GEMINI_31_FLASH,
        provider_id="openrouter",
        backend_model="google/gemini-2.0-flash-001",
    ),
    WrapModel.GPT_54_NANO: ModelRoute(
        wrap_model=WrapModel.GPT_54_NANO,
        provider_id="openai",
        backend_model="gpt-4o-mini",
    ),
}


def route_for_model(model: WrapModel) -> ModelRoute:
    """Look up the route, raising ``KeyError`` if the enum gained a value
    without a matching mapping (defensive: ``Enum`` membership is
    enforced by the type, but this catches a stale routing table)."""
    try:
        return MODEL_ROUTES[model]
    except KeyError as exc:
        raise KeyError(
            f"No backend route configured for WrapModel {model!r}. "
            "Add an entry to MODEL_ROUTES."
        ) from exc


__all__ = ["MODEL_ROUTES", "ModelRoute", "route_for_model"]
