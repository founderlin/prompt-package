"""Application factory for the promptpackage backend."""

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
            if "context_metadata" not in cols:
                # R-BLA-NOTE-CHAT: JSON-encoded record of any context
                # items (bla notes, future packs / attachments) that
                # were attached to this message at send time. NULL on
                # legacy rows.
                conn.execute(
                    text("ALTER TABLE messages ADD COLUMN context_metadata TEXT")
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

    # R-WRAPUP: Context Pack grew structured metadata (summary / keywords /
    # description / source_type) plus an optional conversation_id back-link.
    # ContextPackSource + ContextPackJob are whole new tables picked up by
    # db.create_all() automatically.
    #
    # R-PACK-CORE extends ContextPack with extensibility hooks
    # (structured_content, visibility, graph_data, vector_index_id,
    # version, parent_pack_id, usage_count, last_used_at) and relaxes
    # ``project_id`` to NULLABLE. Since SQLite's ALTER TABLE can't change
    # column nullability, that last change requires a one-shot table
    # rebuild — guarded by a probe so it runs at most once per DB.
    if "context_packs" in table_names:
        cols = {c["name"] for c in inspector.get_columns("context_packs")}
        with db.engine.begin() as conn:
            if "summary" not in cols:
                conn.execute(
                    text("ALTER TABLE context_packs ADD COLUMN summary TEXT")
                )
            if "description" not in cols:
                conn.execute(
                    text("ALTER TABLE context_packs ADD COLUMN description TEXT")
                )
            if "keywords" not in cols:
                conn.execute(
                    text("ALTER TABLE context_packs ADD COLUMN keywords TEXT")
                )
            if "source_type" not in cols:
                conn.execute(
                    text(
                        "ALTER TABLE context_packs ADD COLUMN source_type VARCHAR(20)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS "
                        "ix_context_packs_source_type ON context_packs(source_type)"
                    )
                )
            if "conversation_id" not in cols:
                # Per-row FK isn't possible via ALTER TABLE on SQLite; the
                # ORM-side relationship still works off the integer column,
                # and we enforce ownership in the service layer.
                conn.execute(
                    text(
                        "ALTER TABLE context_packs ADD COLUMN conversation_id INTEGER"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS "
                        "ix_context_packs_conversation_id "
                        "ON context_packs(conversation_id)"
                    )
                )
            # R-PACK-CORE extensibility columns.
            if "structured_content" not in cols:
                conn.execute(
                    text("ALTER TABLE context_packs ADD COLUMN structured_content TEXT")
                )
            if "visibility" not in cols:
                conn.execute(
                    text(
                        "ALTER TABLE context_packs ADD COLUMN visibility "
                        "VARCHAR(16) NOT NULL DEFAULT 'private'"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS "
                        "ix_context_packs_user_visibility "
                        "ON context_packs(user_id, visibility)"
                    )
                )
            if "graph_data" not in cols:
                conn.execute(
                    text("ALTER TABLE context_packs ADD COLUMN graph_data TEXT")
                )
            if "vector_index_id" not in cols:
                conn.execute(
                    text(
                        "ALTER TABLE context_packs ADD COLUMN vector_index_id VARCHAR(120)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS "
                        "ix_context_packs_vector_index_id "
                        "ON context_packs(vector_index_id)"
                    )
                )
            if "version" not in cols:
                conn.execute(
                    text(
                        "ALTER TABLE context_packs ADD COLUMN version "
                        "INTEGER NOT NULL DEFAULT 1"
                    )
                )
            if "parent_pack_id" not in cols:
                conn.execute(
                    text(
                        "ALTER TABLE context_packs ADD COLUMN parent_pack_id INTEGER"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS "
                        "ix_context_packs_parent_pack_id "
                        "ON context_packs(parent_pack_id)"
                    )
                )
            if "usage_count" not in cols:
                conn.execute(
                    text(
                        "ALTER TABLE context_packs ADD COLUMN usage_count "
                        "INTEGER NOT NULL DEFAULT 0"
                    )
                )
            if "last_used_at" not in cols:
                conn.execute(
                    text(
                        "ALTER TABLE context_packs ADD COLUMN last_used_at DATETIME"
                    )
                )

        # Relax ``project_id`` from NOT NULL to NULLABLE if needed. We
        # can't do this with ALTER TABLE on SQLite, so we rebuild the
        # table following the official 12-step procedure (condensed):
        #   1. begin txn
        #   2. create ``context_packs_new`` with the desired schema
        #   3. INSERT INTO ... SELECT * FROM old
        #   4. drop old, rename new
        #   5. recreate indexes
        # Runs at most once — detected by inspecting the live schema.
        _rebuild_context_packs_if_project_id_not_null()

    # R-PACK-CORE: ContextPackSource grew typed FK columns (project_id,
    # conversation_id, note_id, attachment_id) + a source_title snapshot.
    if "context_pack_sources" in table_names:
        cols = {c["name"] for c in inspector.get_columns("context_pack_sources")}
        with db.engine.begin() as conn:
            if "project_id" not in cols:
                conn.execute(
                    text("ALTER TABLE context_pack_sources ADD COLUMN project_id INTEGER")
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS "
                        "ix_context_pack_sources_project_id "
                        "ON context_pack_sources(project_id)"
                    )
                )
            if "conversation_id" not in cols:
                conn.execute(
                    text(
                        "ALTER TABLE context_pack_sources ADD COLUMN conversation_id INTEGER"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS "
                        "ix_context_pack_sources_conversation_id "
                        "ON context_pack_sources(conversation_id)"
                    )
                )
            if "note_id" not in cols:
                conn.execute(
                    text("ALTER TABLE context_pack_sources ADD COLUMN note_id INTEGER")
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS "
                        "ix_context_pack_sources_note_id "
                        "ON context_pack_sources(note_id)"
                    )
                )
            if "attachment_id" not in cols:
                conn.execute(
                    text(
                        "ALTER TABLE context_pack_sources ADD COLUMN attachment_id INTEGER"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS "
                        "ix_context_pack_sources_attachment_id "
                        "ON context_pack_sources(attachment_id)"
                    )
                )
            if "source_title" not in cols:
                conn.execute(
                    text(
                        "ALTER TABLE context_pack_sources ADD COLUMN source_title VARCHAR(240)"
                    )
                )
        _backfill_context_pack_source_typed_fks()

    # R14: copy any existing single-key OpenRouter credential into the new
    # ``provider_credentials`` table so the multi-provider service is the
    # only read path going forward. We keep the legacy column populated
    # for one release as a fallback (see credentials_service.save_key).
    if {"users", "provider_credentials"}.issubset(table_names):
        _migrate_legacy_openrouter_keys()


def _rebuild_context_packs_if_project_id_not_null() -> None:
    """Relax ``context_packs.project_id`` from NOT NULL to NULLABLE.

    SQLite can't ALTER COLUMN nullability, so we follow the official
    "create new, copy, swap" rebuild pattern. This runs at most once per
    database — we probe the live schema first and bail if project_id is
    already nullable.

    We intentionally skip this rebuild on non-SQLite backends; on
    Postgres / MySQL this is a single ALTER and will be handled by the
    first real Alembic migration when we get there.
    """
    if db.engine.dialect.name != "sqlite":
        return

    inspector = inspect(db.engine)
    cols_info = {c["name"]: c for c in inspector.get_columns("context_packs")}
    project_col = cols_info.get("project_id")
    if project_col is None:
        return
    # SQLAlchemy inspector reports ``nullable`` accurately for SQLite.
    if project_col.get("nullable", True):
        return  # already nullable, nothing to do

    # Build the new table with the same physical schema except:
    #   * project_id is NULL allowed
    #   * all R-PACK-CORE columns are included from the start
    #
    # We use SQLAlchemy's table metadata instead of hand-rolling the
    # CREATE TABLE so the column list stays in sync with the model.
    with db.engine.begin() as conn:
        # Existing column names (ordered) — we'll copy exactly these over.
        existing_cols = [c["name"] for c in inspector.get_columns("context_packs")]
        existing_indexes = inspector.get_indexes("context_packs")

        col_list = ", ".join(existing_cols)

        # Create the replacement table. We re-declare it here explicitly
        # so the rebuild is self-contained (rather than trusting the
        # ORM's CREATE TABLE, which might differ if the model changes
        # further before this migration re-runs).
        conn.execute(
            text(
                """
                CREATE TABLE context_packs_new (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
                    conversation_id INTEGER REFERENCES conversations(id) ON DELETE SET NULL,
                    title VARCHAR(160) NOT NULL DEFAULT 'Context Pack',
                    description TEXT,
                    body TEXT NOT NULL DEFAULT '',
                    summary TEXT,
                    keywords TEXT,
                    structured_content TEXT,
                    source_type VARCHAR(20),
                    visibility VARCHAR(16) NOT NULL DEFAULT 'private',
                    graph_data TEXT,
                    vector_index_id VARCHAR(120),
                    version INTEGER NOT NULL DEFAULT 1,
                    parent_pack_id INTEGER REFERENCES context_packs(id) ON DELETE SET NULL,
                    usage_count INTEGER NOT NULL DEFAULT 0,
                    last_used_at DATETIME,
                    model VARCHAR(120),
                    instructions TEXT,
                    source_memory_ids TEXT,
                    memory_count INTEGER NOT NULL DEFAULT 0,
                    prompt_tokens INTEGER,
                    completion_tokens INTEGER,
                    total_tokens INTEGER,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )

        # Copy every existing row across. We only copy columns that exist
        # on BOTH sides so the migration survives mid-deploy restarts.
        new_cols = {
            "id", "user_id", "project_id", "conversation_id", "title",
            "description", "body", "summary", "keywords",
            "structured_content", "source_type", "visibility",
            "graph_data", "vector_index_id", "version", "parent_pack_id",
            "usage_count", "last_used_at", "model", "instructions",
            "source_memory_ids", "memory_count", "prompt_tokens",
            "completion_tokens", "total_tokens", "created_at", "updated_at",
        }
        shared = [c for c in existing_cols if c in new_cols]
        shared_list = ", ".join(shared)
        conn.execute(
            text(
                f"INSERT INTO context_packs_new ({shared_list}) "
                f"SELECT {shared_list} FROM context_packs"
            )
        )

        conn.execute(text("DROP TABLE context_packs"))
        conn.execute(
            text("ALTER TABLE context_packs_new RENAME TO context_packs")
        )

        # Recreate indexes we know about. We intentionally don't restore
        # every historical index — the ORM's Index declarations in
        # context_pack.py will be materialized by the next db.create_all()
        # call (which is idempotent thanks to IF NOT EXISTS).
        for idx in existing_indexes:
            name = idx.get("name")
            if not name:
                continue
            cols = idx.get("column_names") or []
            if not cols:
                continue
            unique = "UNIQUE " if idx.get("unique") else ""
            conn.execute(
                text(
                    f"CREATE {unique}INDEX IF NOT EXISTS {name} "
                    f"ON context_packs ({', '.join(cols)})"
                )
            )
        # Explicitly ensure the R-PACK-CORE indexes exist even when the
        # source DB didn't have them at the time of the snapshot.
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_context_packs_user_visibility "
                "ON context_packs(user_id, visibility)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_context_packs_parent_pack_id "
                "ON context_packs(parent_pack_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_context_packs_vector_index_id "
                "ON context_packs(vector_index_id)"
            )
        )


def _backfill_context_pack_source_typed_fks() -> None:
    """Populate the new typed FK columns for any pre-existing rows.

    The wrap-up flow before R-PACK-CORE wrote every row with a
    ``source_type`` + generic ``source_id`` only. After the migration
    that added ``project_id`` / ``conversation_id`` / ``note_id`` /
    ``attachment_id``, the historic rows are missing the typed FK.
    This one-shot pass copies ``source_id`` into the matching column
    so the new indexed lookups find them.

    Runs every boot but is cheap — it UPDATEs only rows whose typed
    column is still NULL for their declared type.
    """
    with db.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE context_pack_sources SET project_id = source_id "
                "WHERE source_type = 'project' AND project_id IS NULL "
                "AND source_id IS NOT NULL"
            )
        )
        conn.execute(
            text(
                "UPDATE context_pack_sources SET conversation_id = source_id "
                "WHERE source_type = 'conversation' AND conversation_id IS NULL "
                "AND source_id IS NOT NULL"
            )
        )
        conn.execute(
            text(
                "UPDATE context_pack_sources SET note_id = source_id "
                "WHERE source_type = 'note' AND note_id IS NULL "
                "AND source_id IS NOT NULL"
            )
        )
        conn.execute(
            text(
                "UPDATE context_pack_sources SET attachment_id = source_id "
                "WHERE source_type = 'attachment' AND attachment_id IS NULL "
                "AND source_id IS NOT NULL"
            )
        )


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
