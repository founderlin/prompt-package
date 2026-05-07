# syntax=docker/dockerfile:1.6
#
# Backend Dockerfile — Prompt Package (Flask + gunicorn).
#
# Two-stage build:
#   1. ``deps``  — installs Python dependencies in a throw-away layer so
#                  the final image doesn't keep pip's caches or the apt
#                  build toolchain.
#   2. ``final`` — copies the site-packages + app source, runs as a
#                  non-root user, exposes port 5001, starts gunicorn.
#
# The image is fully self-contained; the SQLite file lives under
# /app/instance which the compose file mounts as a named volume so
# container rebuilds don't lose data.

# ---------- Stage 1: build deps ----------
FROM python:3.11-slim AS deps

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# cryptography + pypdf need a compiler only when wheels are unavailable.
# python:3.11-slim on linux/amd64 and linux/arm64 already has prebuilt
# wheels for every dep, so we skip build-essential by default. If you
# target an exotic arch and pip starts compiling from source, uncomment
# the apt block below.
#
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     build-essential libffi-dev && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --prefix=/install -r requirements.txt \
    && pip install --prefix=/install gunicorn==23.0.0

# ---------- Stage 2: final runtime image ----------
FROM python:3.11-slim AS final

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_HOST=0.0.0.0 \
    FLASK_PORT=5001

# Curl is handy for healthchecks; tini reaps zombies on SIGTERM.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl tini \
    && rm -rf /var/lib/apt/lists/*

# Non-root user — good hygiene, and avoids root-owned files showing up
# in the mounted /app/instance volume on the host.
RUN useradd --create-home --uid 10001 --shell /bin/bash promptpkg

WORKDIR /app

COPY --from=deps /install /usr/local

# Copy only what the runtime needs. Tests / scripts stay out of the image.
COPY --chown=promptpkg:promptpkg app ./app
COPY --chown=promptpkg:promptpkg app.py config.py ./

# Persisted state (SQLite + uploads): owned by the app user so the
# volume mount inherits sane permissions on first boot.
RUN mkdir -p /app/instance && chown -R promptpkg:promptpkg /app

USER promptpkg
EXPOSE 5001

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD curl --fail --silent http://127.0.0.1:5001/api/health || exit 1

# tini as PID 1 → clean signal handling, no zombie processes.
# gunicorn args:
#   --factory                : tell gunicorn that the target is a
#                              callable returning the WSGI app, not
#                              a bare ``app`` attribute. We use this
#                              because the repo ships both ``app/``
#                              (Python package, has ``create_app``) and
#                              ``app.py`` (script, has a bare ``app``);
#                              Python's import system prefers the
#                              package, so ``app:app`` can't find the
#                              attribute. Factory mode sidesteps the
#                              conflict entirely.
#   -w 4                     : 4 worker processes (SQLite writes serialize,
#                              but reads benefit from parallelism).
#   --timeout 120            : chat_completion can take ~60s on big prompts.
#   --access-logfile -       : logs to stdout so `docker logs` shows them.
#   --graceful-timeout 30    : give in-flight LLM calls time to finish.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["gunicorn", \
     "--factory", \
     "-w", "4", \
     "-b", "0.0.0.0:5001", \
     "--timeout", "120", \
     "--graceful-timeout", "30", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "app:create_app"]
