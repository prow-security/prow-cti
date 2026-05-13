# Database migrations

PostgreSQL 16+ with the `pg_trgm` extension. Apply from the repository root:

```bash
export PROW_DATABASE_URL=postgresql+asyncpg://prow:prow@127.0.0.1:5432/prow
python -m alembic upgrade head
```

Local Postgres via Compose: `docker compose -f docker-compose.postgres.yml up -d`.

Downgrade (dev only):

```bash
python -m alembic downgrade base
```
