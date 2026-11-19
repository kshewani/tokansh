#!/usr/bin/env bash
# Local application services only. Never manages DRUNIX or database migrations.
set -euo pipefail
REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
PY="$REPO/backend/.venv/bin/python"
[[ -x "$PY" ]] || { echo 'Missing backend virtual environment; complete manual backend setup first.' >&2; exit 1; }
exec "$PY" -B "$REPO/scripts/tokansh_app.py" "$@"
