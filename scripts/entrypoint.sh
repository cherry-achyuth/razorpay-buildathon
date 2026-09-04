#!/bin/sh
set -e

echo "==> Running database migrations with Alembic..."
alembic upgrade head

echo "==> Starting DecisionVault Uvicorn server on port ${PORT:-8000}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
