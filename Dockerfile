# ---- 1) frontend (React + Vite) ----
# roda na plataforma nativa do build: o resultado é HTML/JS, igual para amd64 e arm64
FROM --platform=$BUILDPLATFORM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- 2) API + worker (Python) com ffmpeg ----
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    DATA_DIR=/data \
    FRONTEND_DIST=/app/frontend/dist

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY backend/app ./app
COPY --from=web /web/dist /app/frontend/dist

RUN useradd --create-home --uid 1000 studio && mkdir -p /data && chown -R studio:studio /data
USER studio
VOLUME ["/data"]
EXPOSE 8000

# mesmo imagem para os dois serviços:  api (padrão)  |  worker  |  all (api + worker juntos)  |  migrate
ENTRYPOINT ["python", "-m", "app"]
CMD ["api"]
