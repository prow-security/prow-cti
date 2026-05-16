#!/bin/sh
set -e

echo "Prow CTI starting..."

# 1. Wait for Postgres to be ready
echo "Waiting for database..."
until python -c "
import asyncio, asyncpg, os, sys

def dsn():
    url = os.environ['PROW_DATABASE_URL']
    return url.replace('postgresql+asyncpg://', 'postgresql://', 1)

async def check():
    try:
        conn = await asyncpg.connect(dsn())
        await conn.close()
    except Exception:
        sys.exit(1)

asyncio.run(check())
" 2>/dev/null; do
    sleep 1
done
echo "Database ready."

# 2. Run Alembic migrations
echo "Running migrations..."
alembic upgrade head
echo "Migrations complete."

# 3. First-boot KEV ingestion when DB is empty and cisa-kev is enabled in config
OBJECT_COUNT=$(python -c "
import asyncio, asyncpg, os

def dsn():
    url = os.environ['PROW_DATABASE_URL']
    return url.replace('postgresql+asyncpg://', 'postgresql://', 1)

async def count():
    conn = await asyncpg.connect(dsn())
    row = await conn.fetchrow('SELECT COUNT(*) as c FROM stix_objects')
    await conn.close()
    print(row['c'])

asyncio.run(count())
" 2>/dev/null || echo "0")

if [ "$OBJECT_COUNT" = "0" ]; then
    KEV_ENABLED=$(python -c "
from prow.config import load_config
cfg = load_config()
enabled = any(
    c.name == 'cisa-kev' and c.enabled
    for c in cfg.connectors
)
print('true' if enabled else 'false')
" 2>/dev/null || echo "true")

    if [ "$KEV_ENABLED" = "true" ]; then
        echo "First boot — ingesting CISA KEV..."
        prow connector dev --no-watch --persist \
            src/prow/connectors/kev || true
        echo "KEV ingestion complete."
    else
        echo "Empty database — cisa-kev disabled in config, skipping initial ingest."
    fi
else
    echo "Data exists ($OBJECT_COUNT objects) — skipping initial ingest."
fi

# 4. Start the API server (supervisor + scheduler start in app lifespan)
echo "Starting Prow CTI on port 8000..."
exec python -m prow
