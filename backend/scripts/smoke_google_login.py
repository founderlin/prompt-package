"""Smoke-test R15: Google Sign-In via GIS id_token.

Run from ``backend/`` with the venv active:

    python scripts/smoke_google_login.py

All Google network calls are monkey-patched so this is offline / no
``GOOGLE_CLIENT_ID`` needs to actually exist on Google's side.

Verifies:

* Without ``GOOGLE_CLIENT_ID`` configured, the route returns 503.
* A malformed / invalid id_token is rejected with 401.
* A first-time Google login creates a passwordless user with
  ``google_sub`` / ``google_email`` filled and ``auth_provider='google'``.
* A second login with the same ``sub`` reuses the same row (no dupes).
* A login whose ``email_verified=True`` matches an existing password user
  links Google onto that row and preserves the original password.
* A login whose ``email_verified=False`` does NOT auto-link (it falls
  through to "create new account").
* ``User.to_dict()`` reports ``google_linked`` / ``has_password`` / 
  ``auth_provider`` correctly.

Prints PASS/FAIL and exits non-zero on any assertion error.
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.setdefault("SECRET_KEY", "smoke-secret")
os.environ.setdefault("JWT_SECRET_KEY", "smoke-jwt")
# We override per-case below; default to enabled so most tests can run.
os.environ["GOOGLE_CLIENT_ID"] = "test-client-id.apps.googleusercontent.com"

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import User  # noqa: E402
from app.services import auth_service  # noqa: E402

PASS = "[PASS]"
FAIL = "[FAIL]"


def _claims(sub: str, email: str | None, *, verified: bool = True) -> dict:
    out = {
        "iss": "https://accounts.google.com",
        "aud": "test-client-id.apps.googleusercontent.com",
        "sub": sub,
        "exp": 9_999_999_999,
        "iat": 1_700_000_000,
    }
    if email is not None:
        out["email"] = email
        out["email_verified"] = verified
    return out


def run() -> int:
    app = create_app()
    with app.app_context():
        client = app.test_client()

        # ---- 1. Disabled when GOOGLE_CLIENT_ID is empty ----
        with patch.dict(app.config, {"GOOGLE_CLIENT_ID": None}):
            resp = client.post("/api/auth/google", json={"id_token": "anything"})
            assert resp.status_code == 503, resp.data
            body = resp.get_json()
            assert body["error"] == "google_login_disabled"
            cfg_resp = client.get("/api/auth/google/config")
            assert cfg_resp.get_json()["enabled"] is False
            print(f"{PASS} 503 + config flag when GOOGLE_CLIENT_ID is unset")

        # ---- 2. Invalid token rejected with 401 ----
        with patch(
            "app.services.auth_service._verify_google_id_token",
            side_effect=auth_service.AuthError(
                "invalid_google_token", "boom", status=401
            ),
        ):
            resp = client.post("/api/auth/google", json={"id_token": "bad-jwt"})
            assert resp.status_code == 401, resp.data
            assert resp.get_json()["error"] == "invalid_google_token"
            print(f"{PASS} bad id_token rejected with 401")

        # ---- 3. Missing id_token in body ----
        resp = client.post("/api/auth/google", json={})
        assert resp.status_code == 400, resp.data
        assert resp.get_json()["error"] == "validation_error"
        print(f"{PASS} missing id_token → 400")

        # ---- 4. First-time login creates a passwordless user ----
        first_claims = _claims("g-sub-001", "newgooglier@example.com")
        with patch(
            "app.services.auth_service._verify_google_id_token",
            return_value=first_claims,
        ):
            resp = client.post(
                "/api/auth/google", json={"id_token": "dummy-1"}
            )
        assert resp.status_code == 200, resp.data
        body = resp.get_json()
        assert body["user"]["email"] == "newgooglier@example.com"
        assert body["user"]["google_linked"] is True
        assert body["user"]["has_password"] is False
        assert body["user"]["auth_provider"] == "google"
        assert body["token"]
        new_user = db.session.scalar(
            db.select(User).where(User.google_sub == "g-sub-001")
        )
        assert new_user is not None
        assert new_user.google_email == "newgooglier@example.com"
        print(f"{PASS} first-time Google login creates passwordless user")

        # ---- 5. Second login with same sub returns the same row ----
        before_count = db.session.query(User).count()
        with patch(
            "app.services.auth_service._verify_google_id_token",
            return_value=_claims("g-sub-001", "newgooglier@example.com"),
        ):
            resp = client.post(
                "/api/auth/google", json={"id_token": "dummy-1-again"}
            )
        assert resp.status_code == 200, resp.data
        assert resp.get_json()["user"]["id"] == new_user.id
        after_count = db.session.query(User).count()
        assert after_count == before_count, "no new row should be created"
        print(f"{PASS} repeat sub login is idempotent (no dupes)")

        # ---- 6. Verified email links onto an existing password user ----
        legacy = User(email="bob@example.com", auth_provider="password")
        legacy.set_password("legacypass!")
        db.session.add(legacy)
        db.session.commit()
        original_hash = legacy.password_hash

        with patch(
            "app.services.auth_service._verify_google_id_token",
            return_value=_claims("g-sub-002", "bob@example.com", verified=True),
        ):
            resp = client.post(
                "/api/auth/google", json={"credential": "dummy-2"}  # alias
            )
        assert resp.status_code == 200, resp.data
        body = resp.get_json()
        assert body["user"]["id"] == legacy.id, "should link onto bob, not create"
        db.session.refresh(legacy)
        assert legacy.google_sub == "g-sub-002"
        assert legacy.password_hash == original_hash, "must NOT lose password"
        # auth_provider stays as 'password' — they originally signed up with one
        assert legacy.auth_provider == "password"
        # to_dict should reflect both
        snap = legacy.to_dict()
        assert snap["has_password"] is True
        assert snap["google_linked"] is True
        print(f"{PASS} verified-email login links onto existing password user")

        # ---- 7. Unverified email does NOT auto-link ----
        with patch(
            "app.services.auth_service._verify_google_id_token",
            return_value=_claims(
                "g-sub-003", "bob@example.com", verified=False
            ),
        ):
            resp = client.post(
                "/api/auth/google", json={"id_token": "dummy-3"}
            )
        # An attacker shouldn't be able to take over bob's row by claiming
        # bob@example.com as an unverified Google email. Either we create a
        # synthetic account OR we 409. Both are safe — bob's row must NOT
        # have its google_sub silently overwritten to g-sub-003.
        db.session.refresh(legacy)
        assert legacy.google_sub == "g-sub-002", "bob must keep his original Google link"
        if resp.status_code == 200:
            body = resp.get_json()
            assert body["user"]["id"] != legacy.id
            assert body["user"]["email"] != "bob@example.com"
        else:
            # Acceptable alternative outcome: 409 email_taken because the
            # synthetic noreply email already exists. We never want the
            # success path to silently link onto bob.
            assert resp.status_code in (409,), resp.data
        print(f"{PASS} unverified email does not auto-link onto existing user")

        # ---- 8. /api/auth/google/config exposes flag ----
        cfg_resp = client.get("/api/auth/google/config")
        assert cfg_resp.status_code == 200
        cfg_body = cfg_resp.get_json()
        assert cfg_body["enabled"] is True
        assert cfg_body["client_id"] == "test-client-id.apps.googleusercontent.com"
        print(f"{PASS} config endpoint reports enabled + client_id")

    print("All Google sign-in smoke tests passed.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(run())
    except AssertionError as exc:
        print(f"{FAIL} {exc}")
        traceback.print_exc()
        sys.exit(1)
    except Exception:
        print(f"{FAIL} unexpected error")
        traceback.print_exc()
        sys.exit(2)
