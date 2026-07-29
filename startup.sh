#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -x "${ROOT}/antenv/bin/python" ]]; then
  PYTHON="${ROOT}/antenv/bin/python"
else
  PYTHON=python
fi

exec "$PYTHON" -m uvicorn app.main:app \
  --app-dir backend \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --workers 1 \
  --proxy-headers
