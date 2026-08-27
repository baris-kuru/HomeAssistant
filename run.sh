#!/bin/bash
set -e

cd "$(dirname "$0")"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env — fill in ANTHROPIC_API_KEY, FABI_PASSWORD, CANI_PASSWORD"
  exit 1
fi

if [ ! -d .venv ]; then
  echo "Creating virtualenv..."
  python3 -m venv .venv
fi

source .venv/bin/activate

if [ "${1:-}" = "--bootstrap" ]; then
  pip install -q -r requirements.txt
fi

echo "Starting Persona at https://localhost:8001"
if [ "${HA_DEV_RELOAD:-}" = "1" ]; then
  uvicorn backend.main:app --reload --host 0.0.0.0 --port 8001 --ssl-keyfile key.pem --ssl-certfile cert.pem
else
  uvicorn backend.main:app --host 0.0.0.0 --port 8001 --ssl-keyfile key.pem --ssl-certfile cert.pem
fi
