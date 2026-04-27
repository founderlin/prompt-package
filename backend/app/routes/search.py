"""Search endpoint (R10).

* ``GET /api/search?q=<term>&type=all|messages|memories|conversations&limit=N``

Currently a single endpoint that returns three parallel result lists. We
keep the response shape future-proof by always emitting all three buckets;
callers ignore the buckets they didn't ask for.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.services.search_service import SearchError, search
from app.utils.auth import get_current_user, login_required

search_bp = Blueprint("search", __name__)


def _error(err: SearchError):
    return jsonify({"error": err.code, "message": err.message}), err.status


@search_bp.get("")
@login_required
def index():
    user = get_current_user()
    q = request.args.get("q", "")
    raw_types = request.args.getlist("type") or request.args.get("types")
    limit = request.args.get("limit")
    try:
        payload = search(user, q, types=raw_types, limit=limit)
    except SearchError as err:
        return _error(err)
    return jsonify(payload)
