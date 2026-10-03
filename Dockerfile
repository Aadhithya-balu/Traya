# syntax=docker/dockerfile:1

FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.14-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FACE_MODELS_DIR=/models

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0t64 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY --from=web /web/dist /app/frontend/dist

ARG FETCH_MODELS=true
RUN if [ "$FETCH_MODELS" = "true" ]; then \
        python scripts/fetch_biometric_models.py; \
    fi

RUN useradd --create-home --uid 10001 traya \
    && chown -R traya:traya /app /models
USER traya

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/health').read()"

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
