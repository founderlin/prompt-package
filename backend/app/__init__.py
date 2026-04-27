"""Application factory for the imrockey backend."""

from __future__ import annotations

import logging

from flask import Flask, jsonify, request
from flask_cors import CORS
from sqlalchemy import inspect, text
from werkzeug.exceptions import HTTPException

from config import BaseConfig, get_config

from .extensions import db
from .routes import register_blueprints


def create_app(config_class: type[BaseConfig] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class or get_config())

    _configure_logging(app)

    CORS(
        app,
        resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}},
        supports_credentials=True,
    )

    db.init_app(app)

    # Lightweight schema bootstrap for MVP. Replace with Alembic later.
    with app.app_context():
        # Import models so SQLAlchemy registers them before create_all().
        from . import models  # noqa: F401

        db.create_all()
        _apply_lightweight_migrations()

    register_blueprints(app)
    _register_error_handlers(app)

    return app


def _configure_logging(app: Flask) -> None:
    """Make sure unhandled exceptions hit a real logger.

    Flask's default logger is fine, but in production we want INFO-level
    logging on by default so deployments can see access + warning entries
    without flipping any extra switches.
    """
    if not app.logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "[%(asctime)s] %(levelname)s in %(name)s: %(message)s"
        )
        handler.setFormatter(formatter)
        app.logger.addHandler(handler)
    app.logger.setLevel(logging.DEBUG if app.config.get("DEBUG") else logging.INFO)


def _apply_lightweight_migrations() -> None:
    """SQLite-friendly column additions for MVP.

    ``db.create_all()`` only creates *new* tables; it never alters existing
    ones. As long as we're on SQLite + a single dev DB file, we just inspect
    the live schema and tack on whatever columns are missing.
    """
    inspector = inspect(db.engine)
    table_names = set(inspector.get_table_names())

    if "conversations" in table_names:
        cols = {c["name"] for c in inspector.get_columns("conversations")}
        with db.engine.begin() as conn:
            if "summary" not in cols:
                conn.execute(text("ALTER TABLE conversations ADD COLUMN summary TEXT"))
            if "summarized_at" not in cols:
                conn.execute(
                    text("ALTER TABLE conversations ADD COLUMN summarized_at DATETIME")
                )
            if "context_pack_id" not in cols:
                # R13: SQLite ALTER TABLE … ADD COLUMN can't add an inline FK,
                # but it doesn't need to — SQLAlchemy relationships work off
                # the integer column alone, and we enforce ownership in code.
                conn.execute(
                    text("ALTER TABLE conversations ADD COLUMN context_pack_id INTEGER")
                )
            if "provider" not in cols:
                # R14: which gateway answered each turn. NULL on legacy rows.
                conn.execute(
                    text("ALTER TABLE conversations ADD COLUMN provider VARCHAR(40)")
                )

    if "messages" in table_names:
        cols = {c["name"] for c in inspector.get_columns("messages")}
        with db.engine.begin() as conn:
            if "provider" not in cols:
                # R14: per-message provider stamp (NULL ⇒ legacy).
                conn.execute(
                    text("ALTER TABLE messages ADD COLUMN provider VARCHAR(40)")
                )

    if "users" in table_names:
        # R15: Google Sign-In support adds 3 columns. ``google_sub`` is
        # unique but SQLite ALTER TABLE can't tack on a UNIQUE constraint
        # inline, so we add the column then create a unique index out-of-line.
        cols = {c["name"] for c in inspector.get_columns("users")}
        with db.engine.begin() as conn:
            if "google_sub" not in cols:
                conn.execute(
                    text("ALTER TABLE users ADD COLUMN google_sub VARCHAR(64)")
                )
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS "
                        "ix_users_google_sub ON users(google_sub)"
                    )
                )
            if "google_email" not in cols:
                conn.execute(
                    text("ALTER TABLE users ADD COLUMN google_email VARCHAR(255)")
                )
            if "auth_provider" not in cols:
                conn.execute(
                    text("ALTER TABLE users ADD COLUMN auth_provider VARCHAR(20)")
                )

    # R14: copy any existing single-key OpenRouter credential into the new
    # ``provider_credentials`` table so the multi-provider service is the
    # only read path going forward. We keep the legacy column populated
    # for one release as a fallback (see credentials_service.save_key).
    if {"users", "provider_credentials"}.issubset(table_names):
        _migrate_legacy_openrouter_keys()


def _migrate_legacy_openrouter_keys() -> None:
    from datetime import datetime, timezone

    with db.engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT id, openrouter_api_key_encrypted, updated_at "
                "FROM users "
                "WHERE openrouter_api_key_encrypted IS NOT NULL "
                "  AND openrouter_api_key_encrypted != ''"
            )
        ).fetchall()
        if not rows:
            return

        for user_id, cipher, updated_at in rows:
            already = conn.execute(
                text(
                    "SELECT id FROM provider_credentials "
                    "WHERE user_id = :uid AND provider = 'openrouter'"
                ),
                {"uid": user_id},
            ).first()
            if already is not None:
                continue
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                text(
                    "INSERT INTO provider_credentials "
                    "(user_id, provider, encrypted_api_key, created_at, updated_at) "
                    "VALUES (:uid, 'openrouter', :ck, :now, :now)"
                ),
                {"uid": user_id, "ck": cipher, "now": now},
            )


def _register_error_handlers(app: Flask) -> None:
    """Make sure every error leaving the API is JSON.

    Flask's default 404/500 returns text/html with a stack trace in debug
    mode. The frontend only ever expects JSON on /api/*, so we coerce
    every error path to ``{error, message}`` with the right status code.
    """

    @app.errorhandler(400)
    def _bad_request(err):
        return _json_error(
            "bad_request",
            getattr(err, "description", None) or "Bad request.",
            400,
        )

    @app.errorhandler(401)
    def _unauthorized(err):
        return _json_error(
            "unauthorized",
            getattr(err, "description", None) or "Authentication required.",
            401,
        )

    @app.errorhandler(403)
    def _forbidden(err):
        return _json_error(
            "forbidden",
            getattr(err, "description", None) or "You do not have access to this resource.",
            403,
        )

    @app.errorhandler(404)
    def _not_found(_err):
        return _json_error("not_found", "Resource not found.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_err):
        return _json_error("method_not_allowed", "Method not allowed.", 405)

    @app.errorhandler(422)
    def _unprocessable(err):
        return _json_error(
            "unprocessable_entity",
            getattr(err, "description", None) or "The request was not understood.",
            422,
        )

    @app.errorhandler(HTTPException)
    def _generic_http(err: HTTPException):
        # Catches anything we didn't list above (e.g. 408, 429, 503) and
        # renders it as JSON instead of HTML.
        return _json_error(
            err.name.lower().replace(" ", "_") if err.name else "http_error",
            err.description or "Request failed.",
            err.code or 500,
        )

    @app.errorhandler(Exception)
    def _unhandled(err):
        # Werkzeug HTTPExceptions are already handled above. Anything else
        # is a real bug; log full traceback server-side, return a clean
        # message to the client (no stacktraces leak even in DEBUG).
        app.logger.exception(
            "Unhandled exception while serving %s %s", request.method, request.path
        )
        return _json_error(
            "internal_server_error", "Something went wrong on our side.", 500
        )


def _json_error(code: str, message: str, status: int):
    return jsonify({"error": code, "message": message}), status
