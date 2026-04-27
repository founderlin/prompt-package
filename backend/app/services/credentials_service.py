"""Per-provider credential management.

Replaces R3's single-OpenRouter ``settings_service``. Each user can stash
one API key per provider; the plaintext never leaves this process.

Storage:
    * Encrypted at rest (Fernet, see :mod:`app.utils.crypto`).
    * Stored in :class:`app.models.ProviderCredential`, one row per
      ``(user_id, provider)`` pair.
    * Verify-on-save by default (defense in depth — typos can't slip past
      the UI silently).

Back-compat:
    * The legacy ``users.openrouter_api_key_encrypted`` column is migrated
      into a row here on first boot post-R14 (handled in
      :func:`app.__init__._apply_lightweight_migrations`). Reads still
      fall back to the column if the migration hasn't run yet.
    * ``settings_service.py`` re-exports the OpenRouter-only helpers
      (``get_decrypted_key`` / ``save_openrouter_key`` / etc.) so older
      callers keep working.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.extensions import db
from app.models import ProviderCredential, User
from app.providers import SUPPORTED_PROVIDERS, get_provider
from app.services.llm_service import KeyInfo, LLMError, verify_api_key
from app.utils.crypto import decrypt, encrypt


# ---------- Errors ---------------------------------------------------------------


class CredentialsError(Exception):
    """Predictable, user-facing credential failures."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


MIN_KEY_LEN = 12
MAX_KEY_LEN = 512


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_provider(provider: str | None) -> str:
    if not provider or not provider.strip():
        raise CredentialsError("validation_error", "Provider is required.")
    cleaned = provider.strip().lower()
    if cleaned not in SUPPORTED_PROVIDERS:
        raise CredentialsError(
            "validation_error",
            f"Unsupported provider {cleaned!r}. Supported: {', '.join(SUPPORTED_PROVIDERS)}.",
        )
    return cleaned


def _normalize_key(raw: str | None) -> str:
    if raw is None:
        raise CredentialsError("validation_error", "API key is required.")
    cleaned = raw.strip()
    if not cleaned:
        raise CredentialsError("validation_error", "API key is required.")
    if len(cleaned) < MIN_KEY_LEN or len(cleaned) > MAX_KEY_LEN:
        raise CredentialsError("validation_error", "API key looks malformed.")
    return cleaned


def mask_key(plaintext: str) -> str:
    if not plaintext:
        return ""
    visible_tail = plaintext[-4:]
    if len(plaintext) <= 8:
        return "•" * len(plaintext)
    head_len = min(8, len(plaintext) - 4)
    return f"{plaintext[:head_len]}{'•' * 6}{visible_tail}"


# ---------- Lookup ---------------------------------------------------------------


def _find_row(user: User, provider: str) -> ProviderCredential | None:
    stmt = (
        select(ProviderCredential)
        .where(
            ProviderCredential.user_id == user.id,
            ProviderCredential.provider == provider,
        )
        .limit(1)
    )
    return db.session.scalar(stmt)


def _list_rows(user: User) -> list[ProviderCredential]:
    stmt = select(ProviderCredential).where(ProviderCredential.user_id == user.id)
    return list(db.session.scalars(stmt).all())


def get_decrypted_key_for(user: User, provider: str) -> str | None:
    """Return plaintext key for ``user``+``provider``, or ``None`` if absent."""
    provider = _normalize_provider(provider)
    row = _find_row(user, provider)
    if row is not None:
        try:
            return decrypt(row.encrypted_api_key)
        except Exception as exc:  # InvalidToken or similar
            raise CredentialsError(
                "decryption_failed",
                f"Stored {provider} key could not be decrypted. Please re-enter it.",
                status=500,
            ) from exc

    # Legacy fall-through: pre-R14 users may still have the openrouter key
    # only on the User row if migration hasn't fired yet.
    if provider == "openrouter" and user.openrouter_api_key_encrypted:
        try:
            return decrypt(user.openrouter_api_key_encrypted)
        except Exception as exc:
            raise CredentialsError(
                "decryption_failed",
                "Stored openrouter key could not be decrypted. Please re-enter it.",
                status=500,
            ) from exc
    return None


def status_for(user: User, provider: str) -> dict:
    provider = _normalize_provider(provider)
    cfg = get_provider(provider)
    base: dict = {
        "provider": provider,
        "label": cfg.label,
        "configured": False,
    }

    row = _find_row(user, provider)
    plaintext: str | None = None
    if row is not None:
        try:
            plaintext = decrypt(row.encrypted_api_key)
        except Exception:
            return {**base, "configured": True, "broken": True}
        base.update(
            {
                "configured": True,
                "masked": mask_key(plaintext),
                "key_label": row.label,
                "usage": row.usage,
                "limit": row.limit,
                "limit_remaining": row.limit_remaining,
                "is_free_tier": row.is_free_tier,
                "last_verified_at": (
                    row.last_verified_at.isoformat()
                    if row.last_verified_at is not None
                    else None
                ),
                "updated_at": (
                    row.updated_at.isoformat() if row.updated_at is not None else None
                ),
            }
        )
        return base

    # Legacy openrouter key still in users table.
    if provider == "openrouter" and user.openrouter_api_key_encrypted:
        try:
            plaintext = decrypt(user.openrouter_api_key_encrypted)
        except Exception:
            return {**base, "configured": True, "broken": True}
        base.update(
            {
                "configured": True,
                "masked": mask_key(plaintext),
                "updated_at": (
                    user.updated_at.isoformat() if user.updated_at else None
                ),
            }
        )
    return base


def list_status(user: User) -> list[dict]:
    return [status_for(user, p) for p in SUPPORTED_PROVIDERS]


# ---------- Mutations ------------------------------------------------------------


def _apply_key_info(row: ProviderCredential, info: KeyInfo | None) -> None:
    if info is None:
        return
    if info.label is not None:
        row.label = info.label
    if info.usage is not None:
        row.usage = info.usage
    if info.limit is not None:
        row.limit = info.limit
    if info.limit_remaining is not None:
        row.limit_remaining = info.limit_remaining
    if info.is_free_tier is not None:
        row.is_free_tier = info.is_free_tier
    row.last_verified_at = _utcnow()


def save_key(
    user: User, provider: str, raw_key: str, *, verify: bool = True
) -> tuple[KeyInfo | None, dict]:
    """Validate (optionally) and persist a new key for ``user``+``provider``."""
    provider = _normalize_provider(provider)
    plaintext = _normalize_key(raw_key)

    info: KeyInfo | None = None
    if verify:
        try:
            info = verify_api_key(plaintext, provider=provider)
        except LLMError as err:
            raise CredentialsError(err.code, err.message, status=err.status) from err

    row = _find_row(user, provider)
    if row is None:
        row = ProviderCredential(
            user_id=user.id,
            provider=provider,
            encrypted_api_key=encrypt(plaintext),
        )
    else:
        row.encrypted_api_key = encrypt(plaintext)
    _apply_key_info(row, info)
    db.session.add(row)

    # Mirror to the legacy column for one release so downgrades don't
    # silently lose the openrouter key.
    if provider == "openrouter":
        user.openrouter_api_key_encrypted = row.encrypted_api_key
        db.session.add(user)

    db.session.commit()
    return info, status_for(user, provider)


def delete_key(user: User, provider: str) -> dict:
    provider = _normalize_provider(provider)
    row = _find_row(user, provider)
    if row is not None:
        db.session.delete(row)
    if provider == "openrouter" and user.openrouter_api_key_encrypted:
        user.openrouter_api_key_encrypted = None
        db.session.add(user)
    db.session.commit()
    return status_for(user, provider)


def test_key(user: User, provider: str, raw_key: str | None) -> KeyInfo:
    """Test connectivity using ``raw_key`` if supplied, else the stored key."""
    provider = _normalize_provider(provider)
    if raw_key is not None and raw_key.strip():
        plaintext = _normalize_key(raw_key)
    else:
        stored = get_decrypted_key_for(user, provider)
        if not stored:
            raise CredentialsError(
                "no_api_key",
                "No API key on file — paste one above before testing.",
                status=400,
            )
        plaintext = stored

    try:
        info = verify_api_key(plaintext, provider=provider)
    except LLMError as err:
        raise CredentialsError(err.code, err.message, status=err.status) from err

    # If we just confirmed a stored key, write the freshness back.
    row = _find_row(user, provider)
    if row is not None and (raw_key is None or not raw_key.strip()):
        _apply_key_info(row, info)
        db.session.add(row)
        db.session.commit()

    return info


def first_configured_provider(user: User) -> str | None:
    """Return the first provider this user has a key for, in registry order.

    Used by background jobs (memory / context-pack summary) so that users
    who skipped OpenRouter still get auto-summary working off whichever
    provider they did configure.
    """
    rows = _list_rows(user)
    if rows:
        configured = {r.provider for r in rows}
        for p in SUPPORTED_PROVIDERS:
            if p in configured:
                return p
    if user.openrouter_api_key_encrypted:
        return "openrouter"
    return None


__all__ = [
    "CredentialsError",
    "delete_key",
    "first_configured_provider",
    "get_decrypted_key_for",
    "list_status",
    "mask_key",
    "save_key",
    "status_for",
    "test_key",
]
