#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then python3 -m venv .venv; fi
.venv/bin/python -m pip install -r requirements.txt
if [ ! -d frontend/node_modules ]; then (cd frontend && npm ci --no-audit --no-fund); fi
(cd frontend && npm run build)
.venv/bin/python -m app.cli seed
.venv/bin/python -m app.cli run
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8000}"
