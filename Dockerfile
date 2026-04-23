FROM python:3.11-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y \
    build-essential gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code. The frontend is placed at /frontend so main.py can mount
# it at /app via StaticFiles (path resolved as <backend>/../frontend).
COPY backend/ /app/
COPY frontend/ /frontend/

ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD gunicorn -w 4 -k uvicorn.workers.UvicornWorker \
    --bind "0.0.0.0:${PORT:-8000}" --timeout 120 \
    --access-logfile - --error-logfile - main:app
