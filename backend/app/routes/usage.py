"""Usage metrics endpoints.

Thin wrapper around ``usage_service.summary_for_user``. The frontend
dashboard pulls buckets by granularity and renders the chart from the
returned shape directly.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.services.usage_service import UsageError, summary_for_user
from app.utils.auth import get_current_user, login_required

usage_bp = Blueprint("usage", __name__)


def _error(err: UsageError):
    return jsonify({"error": err.code, "message": err.message}), err.status


@usage_bp.get("/summary")
@login_required
def summary():
    user = get_current_user()
    granularity = request.args.get("granularity", "day")
    try:
        return jsonify(summary_for_user(user, granularity=granularity))
    except UsageError as err:
        return _error(err)
