"""Blueprint registration."""

from __future__ import annotations

from flask import Flask

from .auth import auth_bp
from .context_packs import context_packs_bp
from .conversations import conversations_bp
from .health import health_bp
from .memories import memories_bp
from .projects import projects_bp
from .search import search_bp
from .settings import settings_bp
from .usage import usage_bp


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(health_bp, url_prefix="/api")
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(settings_bp, url_prefix="/api/settings")
    app.register_blueprint(projects_bp, url_prefix="/api/projects")
    app.register_blueprint(conversations_bp, url_prefix="/api/conversations")
    app.register_blueprint(memories_bp, url_prefix="/api/memories")
    app.register_blueprint(context_packs_bp, url_prefix="/api/context-packs")
    app.register_blueprint(search_bp, url_prefix="/api/search")
    app.register_blueprint(usage_bp, url_prefix="/api/usage")
