#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ ! -x .venv/bin/uvicorn ] || [ ! -d frontend/dist ]; then
  echo "Complete the dependency installation and frontend build in README.md first."
  exit 1
fi
exec .venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --timeout-graceful-shutdown 3
