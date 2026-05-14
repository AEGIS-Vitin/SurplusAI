FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Build deps for selectolax (Cython compiled) — only in builder layer
FROM base AS builder
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /tmp/requirements.txt
RUN pip wheel --wheel-dir /wheels -r /tmp/requirements.txt

# ── runtime ──────────────────────────────────────────────────────────
FROM base AS runtime

COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels /wheels/*.whl && rm -rf /wheels

# Backend
COPY backend/app /app/app
# Frontend served from same origin
COPY frontend /app/frontend

ENV CAR_ARBITRAGE_FRONTEND_DIR=/app/frontend \
    CAR_ARBITRAGE_DB=/data/car_arbitrage.sqlite3 \
    PORT=8080

# Volume for SQLite persistence
VOLUME ["/data"]

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health').status == 200 else 1)"

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
