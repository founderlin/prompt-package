"""User settings endpoints (R3 → R14).

R14 added multi-provider support: each user can stash an API key per
provider (OpenRouter / DeepSeek / OpenAI). Endpoints:

* ``GET    /api/settings/providers``                  — list status for all providers
* ``GET    /api/settings/providers/<provider>``       — single provider status
* ``PUT    /api/settings/providers/<provider>/key``   — save / replace key
* ``DELETE /api/settings/providers/<provider>/key``   — remove key
* ``POST   /api/settings/providers/<provider>/test``  — verify connectivity

Legacy (kept as aliases for one release so older clients don't break):

* ``GET/PUT/DELETE/POST /api/settings/openrouter-key`` — same behaviour, ``provider='openrouter'``.

All routes require a valid bearer token. Plaintext keys never leave the
process — encrypted at rest, never echoed back.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.providers import list_providers
from app.services.credentials_service import (
    CredentialsError,
    delete_key,
    list_status,
    save_key,
    status_for,
    test_key,
)
from app.services.model_selection_service import (
    ModelSelectionError,
    add_for_user as add_model_for_user,
    grouped_for_user as grouped_models_for_user,
    list_for_user as list_models_for_user,
    remove_for_user as remove_model_for_user,
    replace_for_provider as replace_models_for_provider,
)
from app.services.settings_service import (
    SettingsError,
    delete_openrouter_key,
    get_status,
    save_openrouter_key,
    test_openrouter_key,
)
from app.utils.auth import get_current_user, login_required

settings_bp = Blueprint("settings", __name__)


def _payload() -> dict:
    return request.get_json(silent=True) or {}


def _error(err: SettingsError | CredentialsError | ModelSelectionError):
    return jsonify({"error": err.code, "message": err.message}), err.status


# ---------- New multi-provider routes (R14) -------------------------------------


@settings_bp.get("/providers")
@login_required
def providers_list():
    user = get_current_user()
    return jsonify(
        {
            "providers": [cfg.to_dict() for cfg in list_providers()],
            "configured": list_status(user),
        }
    )


@settings_bp.get("/providers/<provider>")
@login_required
def provider_status(provider: str):
    user = get_current_user()
    try:
        return jsonify({"provider": status_for(user, provider)})
    except CredentialsError as err:
        return _error(err)


@settings_bp.put("/providers/<provider>/key")
@login_required
def provider_save_key(provider: str):
    user = get_current_user()
    data = _payload()
    raw_key = data.get("api_key")
    skip_verify = bool(data.get("skip_verify"))

    try:
        info, status_obj = save_key(user, provider, raw_key, verify=not skip_verify)
    except CredentialsError as err:
        return _error(err)

    return jsonify(
        {
            "provider": status_obj,
            "key_info": info.to_dict() if info else None,
            "user": user.to_dict(),
        }
    )


@settings_bp.delete("/providers/<provider>/key")
@login_required
def provider_delete_key(provider: str):
    user = get_current_user()
    try:
        status_obj = delete_key(user, provider)
    except CredentialsError as err:
        return _error(err)
    return jsonify({"provider": status_obj, "user": user.to_dict()})


@settings_bp.post("/providers/<provider>/test")
@login_required
def provider_test_key(provider: str):
    user = get_current_user()
    data = _payload()
    raw_key = data.get("api_key")

    try:
        info = test_key(user, provider, raw_key)
    except CredentialsError as err:
        return _error(err)
    return jsonify({"ok": True, "key_info": info.to_dict()})


# ---------- Legacy OpenRouter-only routes (kept as alias) -----------------------


@settings_bp.get("/openrouter-key")
@login_required
def status():
    user = get_current_user()
    return jsonify({"openrouter": get_status(user)})


@settings_bp.put("/openrouter-key")
@login_required
def save():
    user = get_current_user()
    data = _payload()
    raw_key = data.get("api_key")
    skip_verify = bool(data.get("skip_verify"))

    try:
        info, status_obj = save_openrouter_key(user, raw_key, verify=not skip_verify)
    except SettingsError as err:
        return _error(err)

    return jsonify(
        {
            "openrouter": status_obj,
            "key_info": info.to_dict() if info else None,
            "user": user.to_dict(),
        }
    )


@settings_bp.delete("/openrouter-key")
@login_required
def delete():
    user = get_current_user()
    status_obj = delete_openrouter_key(user)
    return jsonify({"openrouter": status_obj, "user": user.to_dict()})


@settings_bp.post("/openrouter-key/test")
@login_required
def test():
    user = get_current_user()
    data = _payload()
    raw_key = data.get("api_key")

    try:
        info = test_openrouter_key(user, raw_key)
    except SettingsError as err:
        return _error(err)

    return jsonify({"ok": True, "key_info": info.to_dict()})


# ---------- Model selection routes ---------------------------------------------
#
# Per-user curated list of which models show up in the chat model picker.
# Stored per provider so the UI can toggle them with provider grouping.


@settings_bp.get("/models")
@login_required
def list_model_selections():
    user = get_current_user()
    grouped = grouped_models_for_user(user)
    flat = list_models_for_user(user)
    return jsonify(
        {
            "models": [row.to_dict() for row in flat],
            "by_provider": {
                provider: [row.to_dict() for row in rows]
                for provider, rows in grouped.items()
            },
        }
    )


@settings_bp.put("/models/<provider>")
@login_required
def replace_model_selections(provider: str):
    user = get_current_user()
    data = _payload()
    models = data.get("models")
    if models is None:
        # Tolerate `{"model_ids": [...]}` as a simple shorthand.
        raw_ids = data.get("model_ids")
        if isinstance(raw_ids, list):
            models = raw_ids
    if models is None or not isinstance(models, list):
        return (
            jsonify(
                {
                    "error": "validation_error",
                    "message": (
                        "Request body must include a `models` list (of "
                        "strings or objects with `model_id`)."
                    ),
                }
            ),
            400,
        )

    try:
        rows = replace_models_for_provider(user, provider=provider, models=models)
    except ModelSelectionError as err:
        return _error(err)
    return jsonify(
        {
            "provider": provider,
            "models": [row.to_dict() for row in rows],
        }
    )


@settings_bp.post("/models/<provider>")
@login_required
def add_model_selection(provider: str):
    user = get_current_user()
    data = _payload()
    try:
        row = add_model_for_user(
            user,
            provider=provider,
            model_id=data.get("model_id"),
            label=data.get("label"),
        )
    except ModelSelectionError as err:
        return _error(err)
    return jsonify({"model": row.to_dict()}), 201


@settings_bp.delete("/models/<provider>/<path:model_id>")
@login_required
def delete_model_selection(provider: str, model_id: str):
    user = get_current_user()
    try:
        remove_model_for_user(user, provider=provider, model_id=model_id)
    except ModelSelectionError as err:
        return _error(err)
    return jsonify({"status": "ok"})
