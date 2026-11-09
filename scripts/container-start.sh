#!/bin/sh
set -eu
python -m app.cli seed
python -m app.cli run
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
