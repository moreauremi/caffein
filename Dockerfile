# syntax=docker/dockerfile:1
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Image Caffein : docker build -t caffein .   puis   docker compose up -d

# ── 1. Interface web (Node uniquement pour le build) ─────────────────────
FROM node:26-alpine AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ── 2. Application Python ────────────────────────────────────────────────
FROM python:3.13-slim

LABEL org.opencontainers.image.title="Caffein" \
      org.opencontainers.image.description="Gestion libre pour freelances et TPE : devis, factures, relances, TVA et URSSAF" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CAFFEIN_DATA_DIR=/data \
    CAFFEIN_HOST=0.0.0.0 \
    CAFFEIN_PORT=8000

RUN groupadd --system --gid 1000 caffein \
 && useradd --system --uid 1000 --gid caffein --home-dir /data --no-create-home --shell /usr/sbin/nologin caffein

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

COPY backend/caffein backend/caffein
COPY --from=frontend /build/frontend/dist frontend/dist
COPY LICENSE README.md ./
COPY deploy/docker-caffein.sh /usr/local/bin/caffein

RUN chmod 755 /usr/local/bin/caffein \
 && mkdir -p /data && chown caffein:caffein /data

USER 1000:1000
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD ["caffein", "health"]

ENTRYPOINT ["caffein"]
CMD ["serve"]
