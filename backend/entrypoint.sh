#!/bin/sh
# Waits for PostgreSQL, applies migrations, and starts the web process.
set -eu

if [ "$#" -gt 0 ]; then
    exec "$@"
fi

mkdir -p "${UPLOAD_DIR:-/data/uploads}"

python - <<'PY'
import os
import time

import psycopg

url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
for attempt in range(60):
    try:
        with psycopg.connect(url, connect_timeout=2):
            break
    except psycopg.OperationalError:
        if attempt == 59:
            raise
        time.sleep(1)
PY

alembic upgrade head
exec gunicorn app.main:app \
    -k uvicorn.workers.UvicornWorker \
    -w 2 \
    -b 0.0.0.0:8000 \
    --forwarded-allow-ips="*" \
    --timeout 60 \
    --max-requests 1000 \
    --max-requests-jitter 100