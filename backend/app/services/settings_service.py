"""Legacy OpenRouter-only credential helpers.

R14 generalized this into :mod:`app.services.credentials_service`. We
keep the original import surface here so older callers (and the smoke
tests) continue to work unchanged.

New code should import from :mod:`app.services.credentials_service`.
"""

from __future__ import annotations

from app.models import User
from app.services.credentials_service import (
    CredentialsError as SettingsError,
    delete_key,
    get_decrypted_key_for,
    mask_key,
    save_key,
    status_for,
    test_key,
)
from app.services.llm_service import KeyInfo as OpenRouterKeyInfo


def get_decrypted_key(user: User) -> str | None:
    return get_decrypted_key_for(user, "openrouter")


def get_status(user: User) -> dict:
    full = status_for(user, "openrouter")
    legacy = {
        "configured": full.get("configured", False),
    }
    if "masked" in full:
        legacy["masked"] = full["masked"]
    if "updated_at" in full:
        legacy["updated_at"] = full["updated_at"]
    if full.get("broken"):
        legacy["broken"] = True
    return legacy


def save_openrouter_key(
    user: User, raw_key: str, *, verify: bool = True
) -> tuple[OpenRouterKeyInfo | None, dict]:
    info, _full_status = save_key(user, "openrouter", raw_key, verify=verify)
    return info, get_status(user)


def delete_openrouter_key(user: User) -> dict:
    delete_key(user, "openrouter")
    return get_status(user)


def test_openrouter_key(user: User, raw_key: str | None) -> OpenRouterKeyInfo:
    return test_key(user, "openrouter", raw_key)


__all__ = [
    "SettingsError",
    "delete_openrouter_key",
    "get_decrypted_key",
    "get_status",
    "mask_key",
    "save_openrouter_key",
    "test_openrouter_key",
]
