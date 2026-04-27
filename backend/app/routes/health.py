"""Health-check endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify

health_bp = Blueprint("health", __name__)


@health_bp.get("/health")
def health_check():
    """Lightweight liveness probe used by the frontend and ops."""
    return jsonify(
        {
            "status": "ok",
            "service": current_app.config.get("APP_NAME", "promptpackage-backend"),
            "version": current_app.config.get("APP_VERSION", "0.0.0"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
