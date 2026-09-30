# mX: one container serving the API and the built web app (design.md §3, §14).
#   docker build -t mx .
#   docker run -p 8000:8000 --env-file .env -v mx-data:/data mx

# --- Stage 1: build the React app -------------------------------------------------
FROM node:24-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# --- Stage 2: the Python app --------------------------------------------------------
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DB_PATH=/data/mx.db \
    WEB_DIST=/app/web/dist
WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY api/ api/
COPY providers/ providers/
COPY prompts/ prompts/
COPY --from=web /web/dist web/dist
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# The app runs as an unprivileged user; the entrypoint only fixes /data ownership
# (volumes are often mounted root-owned) and then drops to this user.
RUN useradd --system --create-home mx && chmod +x /usr/local/bin/docker-entrypoint.sh && mkdir -p /data
VOLUME ["/data"]
EXPOSE 8000

ENTRYPOINT ["docker-entrypoint.sh"]
# --proxy-headers: trust the host's HTTPS proxy (Fly.io) for the client address and scheme.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--timeout-graceful-shutdown", "30"]
