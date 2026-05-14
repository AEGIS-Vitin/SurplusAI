#!/usr/bin/env bash
# Quickstart Car Arbitrage Pro: arranca backend + sirve frontend en localhost:8000
set -euo pipefail

cd "$(dirname "$0")/backend"

if [ ! -d ".venv" ]; then
  echo "→ Creando virtualenv…"
  python3 -m venv .venv
fi

echo "→ Instalando dependencias…"
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt

echo "→ Tests rápidos…"
.venv/bin/python -m pytest tests/ -q

PORT="${PORT:-8000}"
echo
echo "════════════════════════════════════════════════════"
echo "  Car Arbitrage Pro arrancando en http://localhost:${PORT}"
echo "  Pulsa Ctrl+C para parar."
echo "════════════════════════════════════════════════════"
echo

exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "${PORT}"
