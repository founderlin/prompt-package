"""Wrap Up job status endpoint (R-WRAPUP).

* ``GET /api/wrap-up-jobs/<id>`` — poll a wrap-up job's progress.

MVP wrap-ups run synchronously inside the POST that creates them, so
by the time the frontend reads back here the row is almost always
already ``completed`` or ``failed``. The endpoint still exists so:

- The frontend has a stable polling URL to show progress (crucial
  once we move execution to a worker queue).
- Errors are observable even when the original HTTP response was
  dropped (e.g. flaky networks) — frontend code can reconcile by
  refetching the job by id from a toast or link.

Anything not owned by the caller surfaces as 404.
"""

from __future__ import annotations

from flask import Blueprint, jsonify

from app.services.wrap_up_service import WrapUpError, get_job_for_user
from app.utils.auth import get_current_user, login_required

wrap_up_jobs_bp = Blueprint("wrap_up_jobs", __name__)


def _error(err: WrapUpError):
    return jsonify({"error": err.code, "message": err.message}), err.status


@wrap_up_jobs_bp.get("/<int:job_id>")
@login_required
def show(job_id: int):
    user = get_current_user()
    try:
        job = get_job_for_user(user, job_id)
    except WrapUpError as err:
        return _error(err)
    return jsonify({"job": job.to_dict(include_pack=True)})
