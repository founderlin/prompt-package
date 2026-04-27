"""Entrypoint for the promptpackage backend.

Local development:
    python app.py

Production (recommended):
    FLASK_ENV=production \\
    SECRET_KEY=<random> \\
    JWT_SECRET_KEY=<random> \\
    ENCRYPTION_KEY=<Fernet.generate_key()> \\
    gunicorn -w 4 -b 0.0.0.0:5001 'app:app'

The factory imported from ``app/`` is exposed as the WSGI callable
``app`` below, so any standard WSGI server (gunicorn / uwsgi / waitress)
can pick it up directly.
"""

from __future__ import annotations

from app import create_app

app = create_app()


if __name__ == "__main__":
    # Only used for local development. In production, run via gunicorn
    # against the ``app`` callable above.
    app.run(
        host=app.config["HOST"],
        port=app.config["PORT"],
        debug=app.config.get("DEBUG", False),
    )
