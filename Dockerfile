# The hosted site, in two images (see deploy/compose.yaml, which builds both):
#   --target app   the API (uvicorn), with the readers and the copyright agent's tool
#   --target web   Caddy: HTTPS, the built frontend, and /api passed to the app

# --- The frontend, built ---
FROM node:24-slim AS frontend
RUN corepack enable && corepack prepare pnpm@10.27.0 --activate
WORKDIR /src/frontend
COPY frontend/package.json frontend/pnpm-lock.yaml ./
COPY frontend/scripts ./scripts
RUN pnpm install --frozen-lockfile
COPY frontend ./
# The public repository, shown in the footer: the AGPL asks that the site offer its source.
ARG VITE_SOURCE_URL
ENV VITE_SOURCE_URL=$VITE_SOURCE_URL
RUN pnpm build

# --- The API ---
FROM python:3.12-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend ./backend
RUN pip install --no-cache-dir ./backend && rm -rf ./backend
COPY scripts/admin.py ./scripts/admin.py
RUN useradd --system --create-home cbv && mkdir /data && chown cbv /data
USER cbv
ENV CBV_HOSTED=1 CBV_DATA_DIR=/data
VOLUME /data
EXPOSE 8000
# One process: the rate limits and the analysis queue live in its memory. Only Caddy reaches it,
# so the client address it forwards is trusted. No access log: the privacy notice says the site
# keeps none (Caddy keeps none either, as its Caddyfile has no "log").
CMD ["uvicorn", "cbv.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--no-access-log"]

# --- The web server ---
FROM caddy:2 AS web
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=frontend /src/frontend/dist /srv
