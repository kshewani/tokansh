#!/usr/bin/env bash
# Start the TokANSH API on a host such as Render: migrate, seed demo users, serve.
# Safe to run on every boot (migrations and seed are idempotent).
set -euo pipefail
cd "$(dirname "$0")/.."
alembic upgrade head
python -m scripts.seed_demo
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*'
