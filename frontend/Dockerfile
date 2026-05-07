# syntax=docker/dockerfile:1.6
#
# Frontend Dockerfile — Prompt Package (Vue 3 + Vite → Nginx).
#
# Two-stage build:
#   1. ``builder`` — installs npm deps and runs `vite build` with the
#                    VITE_* args baked in at build time. Vite inlines
#                    those into the bundle, so the runtime container
#                    doesn't need them.
#   2. ``final``   — tiny nginx:alpine image serving /usr/share/nginx/html
#                    with a custom nginx.conf that (a) falls back to
#                    index.html for SPA routes, and (b) reverse-proxies
#                    /api/* to the backend container at http://backend:5001.

# ---------- Stage 1: build ----------
FROM node:20-alpine AS builder

WORKDIR /app

# Build-time variables. Both default to values that "just work" when
# the frontend is behind the same origin as the backend via the nginx
# reverse proxy in the final stage.
#   - VITE_API_BASE_URL="" lets axios fall back to relative /api/…
#     paths, which nginx then proxies to the backend service. Use
#     a full URL only when you deploy the frontend on a different
#     origin than the backend and don't want an nginx middle tier.
ARG VITE_API_BASE_URL=""
ARG VITE_GOOGLE_CLIENT_ID=""

ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_GOOGLE_CLIENT_ID=$VITE_GOOGLE_CLIENT_ID

# Prime the dep layer. package-lock.json is tracked so `npm ci` gets a
# reproducible tree; falling back to `npm install` for devs who haven't
# committed the lockfile (e.g. first-time setup).
COPY package.json package-lock.json* ./
RUN if [ -f package-lock.json ]; then \
      npm ci --no-audit --no-fund; \
    else \
      npm install --no-audit --no-fund; \
    fi

COPY . .

RUN npm run build

# ---------- Stage 2: nginx runtime ----------
FROM nginx:1.27-alpine AS final

# Replace the default landing page with our SPA build output.
RUN rm -rf /usr/share/nginx/html/*
COPY --from=builder /app/dist /usr/share/nginx/html

# Custom nginx config: SPA fallback to index.html + /api reverse proxy.
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
  CMD wget --quiet --spider http://127.0.0.1:80/ || exit 1
