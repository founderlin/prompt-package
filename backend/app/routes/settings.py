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


def _error(err: SettingsError | CredentialsError):
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
