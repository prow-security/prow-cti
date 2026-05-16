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

# 3. First-boot KEV ingestion (if no objects exist)
if [ "${PROW_SKIP_KEV_IMPORT:-false}" != "true" ]; then
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
        echo "First boot — ingesting CISA KEV..."
        prow connector dev --no-watch --persist \
            src/prow/connectors/kev || true
        echo "KEV ingestion complete."
    else
        echo "Data exists ($OBJECT_COUNT objects) — skipping initial ingest."
    fi
fi

# 4. Start the API server
echo "Starting Prow CTI on port 8000..."
exec python -m prow
