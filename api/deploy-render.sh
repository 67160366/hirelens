#!/bin/sh
set -eu
python -m app.deploy
alembic upgrade head
# Exactly one process: the database consumer runs in its lifespan, serially.
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1
