#!/usr/bin/env bash
set -Eeuo pipefail

# Resolve repo root (this file lives at backend/scripts/dev-start.sh)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$APP_ROOT"

# Defaults (override by exporting HOST/PORT/LOG_DIR if you want)
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
LOG_DIR="${LOG_DIR:-${APP_ROOT}/logs}"
mkdir -p "$LOG_DIR"
LOG_FILE="${LOG_DIR}/uvicorn-$(date +%Y%m%d-%H%M%S).log"

export PYTHONUNBUFFERED=1

# If a venv exists, use it
if [[ -d ".venv" ]]; then
  # shellcheck source=/dev/null
  source .venv/bin/activate
fi

# Ensure Python deps (quiet install, keeps your current pins)
pip install -r requirements.txt >/dev/null

echo
echo "🟢 MedFax (backend) – dev server"
echo "👉 Open:    http://localhost:${PORT}/"
echo "📚 Docs:    http://localhost:${PORT}/docs"
echo "🔎 Logs:    tail -f \"${LOG_FILE}\""
echo

UVICORN_CMD="uvicorn app.main:app --host ${HOST} --port ${PORT} --reload --log-level debug --use-colors --proxy-headers"

# Show the exact command we run (useful when copy/pasting)
echo "▶︎ ${UVICORN_CMD}"
# Stream stdout/stderr to a log file you can tail
${UVICORN_CMD} 2>&1 | tee "${LOG_FILE}"


# Making a hashed edit so that git will update the file as having a new edit.