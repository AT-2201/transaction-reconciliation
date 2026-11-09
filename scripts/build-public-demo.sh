#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
(
  cd frontend
  VITE_PUBLIC_DEMO=1 npm run build -- --base=./ --outDir=demo-dist
)
"${PYTHON:-python3}" -m scripts.export_public_demo
