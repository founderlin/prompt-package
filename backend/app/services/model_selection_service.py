"""User-curated model selection (which models show up in the chat picker).

A user selects, per provider, which models they actually want to see in
the chat composer's model picker. We persist the selections so they
survive across devices and clears of local storage, and so the chat
route can validate against the user's own allow-list if we ever decide
to tighten that.

Design choices:

* No "default set" is created on signup. An empty list means the
  frontend should show provider setup CTAs and fall back to a safe
  built-in default at chat time.
* ``model_id`` is opaque — we accept anything non-empty so users can
  paste model ids that aren't in our curated constants.
* Upserting by (user_id, provider, model_id) is idempotent; we never
  duplicate rows.
"""

from __future__ import annotations

from typing import Iterable

from sqlalchemy import select

from app.extensions import db
from app.models import User, UserModelSelection
from app.providers import SUPPORTED_PROVIDERS, normalize_provider

MODEL_ID_MAX = 160
LABEL_MAX = 160


class ModelSelectionError(Exception):
    """Predictable, user-facing model-selection failures."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _normalize_provider(raw: str | None) -> str:
    key = (raw or "").strip().lower()
    if not key or key not in SUPPORTED_PROVIDERS:
        raise ModelSelectionError(
            "validation_error",
            f"Unknown provider: {raw!r}.",
            status=422,
        )
    return key


def _normalize_model_id(raw: str | None) -> str:
    if raw is None:
        raise ModelSelectionError("validation_error", "model_id is required.")
    cleaned = raw.strip()
    if not cleaned:
        raise ModelSelectionError("validation_error", "model_id is required.")
    if len(cleaned) > MODEL_ID_MAX:
        raise ModelSelectionError(
            "validation_error",
            f"model_id must be at most {MODEL_ID_MAX} characters.",
        )
    return cleaned


def _normalize_label(raw: str | None) -> str | None:
    if raw is None:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    if len(cleaned) > LABEL_MAX:
        cleaned = cleaned[:LABEL_MAX]
    return cleaned


def list_for_user(user: User) -> list[UserModelSelection]:
    stmt = (
        select(UserModelSelection)
        .where(UserModelSelection.user_id == user.id)
        .order_by(
            UserModelSelection.provider.asc(),
            UserModelSelection.created_at.asc(),
            UserModelSelection.id.asc(),
        )
    )
    return list(db.session.scalars(stmt).all())


def list_for_provider(user: User, provider: str) -> list[UserModelSelection]:
    provider = normalize_provider(provider)
    stmt = (
        select(UserModelSelection)
        .where(
            UserModelSelection.user_id == user.id,
            UserModelSelection.provider == provider,
        )
        .order_by(
            UserModelSelection.created_at.asc(),
            UserModelSelection.id.asc(),
        )
    )
    return list(db.session.scalars(stmt).all())


def grouped_for_user(user: User) -> dict[str, list[UserModelSelection]]:
    """Return selections bucketed by provider, including empty providers."""
    groups: dict[str, list[UserModelSelection]] = {
        p: [] for p in SUPPORTED_PROVIDERS
    }
    for sel in list_for_user(user):
        groups.setdefault(sel.provider, []).append(sel)
    return groups


def add_for_user(
    user: User,
    *,
    provider: str | None,
    model_id: str | None,
    label: str | None = None,
) -> UserModelSelection:
    p = _normalize_provider(provider)
    mid = _normalize_model_id(model_id)
    lbl = _normalize_label(label)

    existing = (
        db.session.query(UserModelSelection)
        .filter_by(user_id=user.id, provider=p, model_id=mid)
        .first()
    )
    if existing is not None:
        # Idempotent: allow updating the label on re-add.
        if lbl is not None and lbl != existing.label:
            existing.label = lbl
            db.session.add(existing)
            db.session.commit()
        return existing

    sel = UserModelSelection(
        user_id=user.id,
        provider=p,
        model_id=mid,
        label=lbl,
    )
    db.session.add(sel)
    db.session.commit()
    return sel


def replace_for_provider(
    user: User,
    *,
    provider: str | None,
    models: Iterable[dict | str] | None,
) -> list[UserModelSelection]:
    """Replace the user's selections for one provider with ``models``.

    ``models`` is an iterable of either plain model id strings or dicts
    like ``{"model_id": "...", "label": "..."}``. Existing rows for this
    provider that aren't in the new list are deleted; new rows are
    inserted; preserved rows keep their timestamps.
    """
    p = _normalize_provider(provider)
    incoming: dict[str, str | None] = {}
    for item in models or []:
        if isinstance(item, str):
            mid = _normalize_model_id(item)
            incoming.setdefault(mid, None)
        elif isinstance(item, dict):
            mid = _normalize_model_id(item.get("model_id"))
            lbl = _normalize_label(item.get("label"))
            incoming[mid] = lbl
        else:
            raise ModelSelectionError(
                "validation_error",
                "models must be strings or objects with a model_id field.",
            )

    current_rows = list_for_provider(user, p)
    keep_ids: set[str] = set()
    for row in current_rows:
        if row.model_id in incoming:
            new_label = incoming[row.model_id]
            if new_label is not None and new_label != row.label:
                row.label = new_label
                db.session.add(row)
            keep_ids.add(row.model_id)
        else:
            db.session.delete(row)

    for mid, lbl in incoming.items():
        if mid in keep_ids:
            continue
        db.session.add(
            UserModelSelection(
                user_id=user.id,
                provider=p,
                model_id=mid,
                label=lbl,
            )
        )

    db.session.commit()
    return list_for_provider(user, p)


def remove_for_user(
    user: User,
    *,
    provider: str | None,
    model_id: str | None,
) -> None:
    p = _normalize_provider(provider)
    mid = _normalize_model_id(model_id)
    row = (
        db.session.query(UserModelSelection)
        .filter_by(user_id=user.id, provider=p, model_id=mid)
        .first()
    )
    if row is None:
        raise ModelSelectionError(
            "not_found", "That model is not in your selection.", status=404
        )
    db.session.delete(row)
    db.session.commit()


def has_any_selection(user: User) -> bool:
    return (
        db.session.query(UserModelSelection.id)
        .filter_by(user_id=user.id)
        .first()
        is not None
    )


__all__ = [
    "ModelSelectionError",
    "add_for_user",
    "grouped_for_user",
    "has_any_selection",
    "list_for_provider",
    "list_for_user",
    "remove_for_user",
    "replace_for_provider",
]
