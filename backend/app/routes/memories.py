"""Memory endpoints (R9).

Listing happens on the project / conversation routes; this blueprint owns
single-memory operations (currently just delete).
"""

from __future__ import annotations

from flask import Blueprint, jsonify

from app.services.memory_service import MemoryError, delete_memory
from app.utils.auth import get_current_user, login_required

memories_bp = Blueprint("memories", __name__)


def _error(err: MemoryError):
    return jsonify({"error": err.code, "message": err.message}), err.status


@memories_bp.delete("/<int:memory_id>")
@login_required
def destroy(memory_id: int):
    user = get_current_user()
    try:
        delete_memory(user, memory_id)
    except MemoryError as err:
        return _error(err)
    return jsonify({"status": "ok"})
