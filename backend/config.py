"""Application configuration objects.

All runtime configuration should flow through here so we keep a single
source of truth. Values are loaded from environment variables (with a
``.env`` file in development) and exposed as plain attributes on the
config classes.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"

load_dotenv(BASE_DIR / ".env")


# Sentinel defaults for dev-only secrets. ProductionConfig refuses to boot
# while any of these is still in use, so a forgotten env var can never
# silently ship to prod.
_DEV_SECRET_KEY = "dev-secret-key-change-me"
_DEV_JWT_SECRET = "dev-jwt-secret-change-me"


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _default_database_url() -> str:
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{(INSTANCE_DIR / 'imrockey.sqlite3').as_posix()}"


class BaseConfig:
    """Shared defaults for every environment."""

    APP_NAME = "imrockey-backend"
    APP_VERSION = "0.1.0"

    SECRET_KEY = os.getenv("SECRET_KEY", _DEV_SECRET_KEY)

    HOST = os.getenv("FLASK_HOST", "127.0.0.1")
    PORT = int(os.getenv("FLASK_PORT", "5001"))

    CORS_ORIGINS = _split_csv(os.getenv("CORS_ORIGINS")) or [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ]

    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", _default_database_url())
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", _DEV_JWT_SECRET)
    JWT_ALGORITHM = "HS256"
    JWT_EXPIRES_DAYS = int(os.getenv("JWT_EXPIRES_DAYS", "30"))

    # Symmetric encryption key for at-rest secrets (e.g. OpenRouter API keys).
    # Must be a 32-byte urlsafe-base64 string produced by ``Fernet.generate_key()``.
    # When unset (dev) we derive a stable key from SECRET_KEY.
    ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

    # R15: Google Sign-In via GIS id_token. When unset, the
    # ``/api/auth/google`` route returns 503 and the frontend hides the
    # button — password login keeps working unchanged.
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID") or None

    # R14: per-provider base URLs (env-overridable). The values referenced
    # here are read by ``app.providers``; an empty/unset env var means
    # "use the official endpoint".
    OPENROUTER_BASE_URL = os.getenv(
        "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
    )
    DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    # Single timeout knob for now — applied to all providers for the cheap
    # verify probe; chat completions get a 6× multiplier inside llm_service.
    OPENROUTER_TIMEOUT_SECONDS = float(os.getenv("OPENROUTER_TIMEOUT_SECONDS", "10"))
    LLM_VERIFY_TIMEOUT_SECONDS = float(
        os.getenv("LLM_VERIFY_TIMEOUT_SECONDS", os.getenv("OPENROUTER_TIMEOUT_SECONDS", "10"))
    )

    JSON_SORT_KEYS = False


class DevelopmentConfig(BaseConfig):
    DEBUG = True


class ProductionConfig(BaseConfig):
    """Production config. Refuses to start with insecure dev defaults."""

    DEBUG = False

    @classmethod
    def assert_safe_for_production(cls) -> None:
        problems: list[str] = []
        if cls.SECRET_KEY == _DEV_SECRET_KEY or not cls.SECRET_KEY:
            problems.append("SECRET_KEY is unset or still on the dev default.")
        if cls.JWT_SECRET_KEY == _DEV_JWT_SECRET or not cls.JWT_SECRET_KEY:
            problems.append(
                "JWT_SECRET_KEY is unset or still on the dev default."
            )
        if not cls.ENCRYPTION_KEY:
            problems.append(
                "ENCRYPTION_KEY is unset; OpenRouter keys would be encrypted "
                "with a value derived from SECRET_KEY (acceptable in dev only)."
            )
        if problems:
            joined = "\n  - " + "\n  - ".join(problems)
            raise RuntimeError(
                "Refusing to start in production with insecure config:" + joined
            )


def get_config() -> type[BaseConfig]:
    env = os.getenv("FLASK_ENV", "development").lower()
    if env in {"prod", "production"}:
        ProductionConfig.assert_safe_for_production()
        return ProductionConfig
    return DevelopmentConfig
