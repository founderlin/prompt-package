"""Symmetric encryption helpers for storing user secrets at rest.

We use Fernet (AES-128-CBC + HMAC) from `cryptography` because it ships
with urlsafe-base64 tokens out of the box and is hard to misuse.

Configuration:
    * If ``ENCRYPTION_KEY`` is set in env / config, we use it directly.
      It must be a 32-byte urlsafe-base64-encoded string (`Fernet.generate_key()`).
    * Otherwise (development convenience) we derive a stable key from
      ``SECRET_KEY`` via SHA-256. Operators are warned in production.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app


def _derive_key_from_secret(secret: str) -> bytes:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _resolve_key() -> bytes:
    raw = current_app.config.get("ENCRYPTION_KEY")
    if raw:
        return raw.encode() if isinstance(raw, str) else raw
    secret = current_app.config.get("SECRET_KEY") or "dev-secret-key-change-me"
    return _derive_key_from_secret(secret)


def _fernet() -> Fernet:
    return Fernet(_resolve_key())


def encrypt(plaintext: str) -> str:
    """Encrypt a UTF-8 string and return a urlsafe-base64 token."""
    if plaintext is None:
        raise ValueError("Cannot encrypt None.")
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(token: str) -> str:
    """Decrypt a token produced by :func:`encrypt`. Raises ``InvalidToken`` if tampered."""
    if not token:
        raise ValueError("Cannot decrypt empty token.")
    return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")


__all__ = ["encrypt", "decrypt", "InvalidToken"]
