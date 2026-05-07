"""Blueprint registration."""

from __future__ import annotations

from flask import Flask

from .auth import auth_bp
from .bla_notes import bla_notes_bp
from .context_packs import context_packs_bp
from .conversations import conversations_bp
from .health import health_bp
from .memories import memories_bp
from .projects import projects_bp
from .search import search_bp
from .settings import settings_bp
from .usage import usage_bp
from .wrap_up_jobs import wrap_up_jobs_bp


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(health_bp, url_prefix="/api")
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(settings_bp, url_prefix="/api/settings")
    app.register_blueprint(projects_bp, url_prefix="/api/projects")
    app.register_blueprint(conversations_bp, url_prefix="/api/conversations")
    app.register_blueprint(memories_bp, url_prefix="/api/memories")
    app.register_blueprint(context_packs_bp, url_prefix="/api/context-packs")
    app.register_blueprint(bla_notes_bp, url_prefix="/api/notes")
    app.register_blueprint(search_bp, url_prefix="/api/search")
    app.register_blueprint(usage_bp, url_prefix="/api/usage")
    app.register_blueprint(wrap_up_jobs_bp, url_prefix="/api/wrap-up-jobs")
