# Copyright 2026 Prow Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text

from prow.db.config import DatabaseSettings
from prow.db.ingest import ingest_stix_bundle
from prow.db.repositories import SqlAlchemyConnectorStateRepository
from prow.db.session import (
    create_async_engine_from_settings,
    create_async_sessionmaker,
    dispose_engine,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _integration_database_url() -> str | None:
    return (
        os.environ.get("DATABASE_URL")
        or os.environ.get("PROW_DATABASE_URL")
        or os.environ.get("PROW_TEST_DATABASE_URL")
    )


def _run_alembic_upgrade(url: str) -> None:
    env = os.environ.copy()
    env["PROW_DATABASE_URL"] = url
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"alembic upgrade failed: {proc.stderr}"


@pytest_asyncio.fixture(scope="module")
async def pg_engine():
    url = _integration_database_url()
    if not url:
        pytest.skip(
            "Set DATABASE_URL, PROW_DATABASE_URL, or PROW_TEST_DATABASE_URL "
            "to a Postgres 16 async DSN for integration tests.",
        )
    _run_alembic_upgrade(url)
    settings = DatabaseSettings(
        database_url=url,
        database_pool_size=5,
        database_pool_max_overflow=2,
        database_pool_timeout_seconds=30.0,
    )
    engine = create_async_engine_from_settings(settings)
    yield engine
    await dispose_engine(engine)


@pytest_asyncio.fixture
async def session_factory(pg_engine):
    return create_async_sessionmaker(pg_engine)


@pytest_asyncio.fixture(autouse=True)
async def truncate_tables(pg_engine):
    async with pg_engine.begin() as conn:
        await conn.execute(
            text("TRUNCATE TABLE stix_objects, connector_state RESTART IDENTITY CASCADE"),
        )
    yield


@pytest.mark.integration
async def test_migration_partial_unique_indexes_exist(pg_engine) -> None:
    async with pg_engine.connect() as conn:
        res = await conn.execute(
            text(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE tablename = 'stix_objects' AND indexname LIKE 'ux_%' "
                "ORDER BY indexname"
            ),
        )
        rows = {r[0]: r[1] for r in res.fetchall()}
    assert "ux_stix_objects_sco_id" in rows
    assert "modified IS NULL" in rows["ux_stix_objects_sco_id"]
    assert "ux_stix_objects_versioned_id_modified" in rows
    assert "modified IS NOT NULL" in rows["ux_stix_objects_versioned_id_modified"]


@pytest.mark.integration
async def test_insert_new_objects(session_factory) -> None:
    bundle = {
        "type": "bundle",
        "id": "bundle--11111111-1111-4111-8111-111111111111",
        "objects": [
            {
                "type": "indicator",
                "spec_version": "2.1",
                "id": "indicator--8e2e2d2b-17d4-4cbf-938f-98ee46b3cd3f",
                "created": "2024-01-01T12:00:00.000Z",
                "modified": "2024-01-01T12:00:00.000Z",
                "pattern": "[ipv4-addr:value = '198.51.100.7']",
                "pattern_type": "stix",
                "valid_from": "2024-01-01T12:00:00.000Z",
            },
        ],
    }
    async with session_factory() as session:
        ack = await ingest_stix_bundle(
            session,
            bundle,
            source_connector_instance_id="inst-a",
        )
    assert ack.accepted == 1
    assert ack.duplicates == 0
    assert ack.validation_failures == []


@pytest.mark.integration
async def test_duplicate_versioned_id_modified_counts_as_duplicate(session_factory) -> None:
    bundle = {
        "type": "bundle",
        "id": "bundle--22222222-2222-4222-8222-222222222222",
        "objects": [
            {
                "type": "indicator",
                "spec_version": "2.1",
                "id": "indicator--aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "created": "2024-01-01T12:00:00.000Z",
                "modified": "2024-01-01T12:00:00.000Z",
                "pattern": "[ipv4-addr:value = '198.51.100.7']",
                "pattern_type": "stix",
                "valid_from": "2024-01-01T12:00:00.000Z",
            },
        ],
    }
    async with session_factory() as session:
        first = await ingest_stix_bundle(session, bundle, source_connector_instance_id="inst-a")
    async with session_factory() as session2:
        second = await ingest_stix_bundle(session2, bundle, source_connector_instance_id="inst-a")
    assert first.accepted == 1
    assert first.duplicates == 0
    assert second.accepted == 0
    assert second.duplicates == 1


@pytest.mark.integration
async def test_duplicate_sco_id_with_null_modified(session_factory) -> None:
    sco = {
        "type": "ipv4-addr",
        "spec_version": "2.1",
        "id": "ipv4-addr--cd0f996f-f345-4528-9707-45cd63f36ddd",
        "value": "198.51.100.3",
    }
    bundle = {
        "type": "bundle",
        "id": "bundle--33333333-3333-4333-8333-333333333333",
        "objects": [sco],
    }
    async with session_factory() as session:
        first = await ingest_stix_bundle(session, bundle, source_connector_instance_id="inst-b")
    async with session_factory() as session2:
        second = await ingest_stix_bundle(session2, bundle, source_connector_instance_id="inst-b")
    assert first.accepted == 1
    assert second.duplicates == 1


@pytest.mark.integration
async def test_two_relationships_same_graph_triple_distinct_ids_preserved(
    session_factory,
    pg_engine,
) -> None:
    campaign = {
        "type": "campaign",
        "spec_version": "2.1",
        "id": "campaign--b549a58c-afd9-4847-85c3-5be13d56d3cc",
        "created": "2014-09-09T19:58:39.609Z",
        "modified": "2014-09-09T19:58:39.609Z",
        "name": "Operation Omega",
    }
    indicator = {
        "type": "indicator",
        "spec_version": "2.1",
        "pattern_type": "stix",
        "name": "test_name",
        "description": "Test description.",
        "id": "indicator--c43a0a05-e8d2-4f64-ae37-3f3fb153f8d9",
        "created": "2014-09-09T19:58:39.609Z",
        "modified": "2014-09-09T19:58:39.609Z",
        "indicator_types": ["malicious-activity"],
        "pattern": "[ ipv4-addr:value = '10.0.0.0' ]",
        "valid_from": "2014-09-09T19:58:39.609000Z",
    }
    rel1 = {
        "type": "relationship",
        "spec_version": "2.1",
        "id": "relationship--eca24e47-2259-4850-9705-fd1065c77236",
        "relationship_type": "indicates",
        "created": "2014-09-09T19:58:39.609Z",
        "modified": "2014-09-09T19:58:39.609Z",
        "source_ref": "indicator--c43a0a05-e8d2-4f64-ae37-3f3fb153f8d9",
        "target_ref": "campaign--b549a58c-afd9-4847-85c3-5be13d56d3cc",
    }
    rel2 = {**rel1, "id": "relationship--bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"}
    bundle = {
        "type": "bundle",
        "id": "bundle--44444444-4444-4444-8444-444444444444",
        "objects": [campaign, indicator, rel1, rel2],
    }
    async with session_factory() as session:
        ack = await ingest_stix_bundle(session, bundle, source_connector_instance_id="inst-c")
    assert ack.accepted == 4
    async with pg_engine.connect() as conn:
        n = await conn.scalar(
            text(
                "SELECT count(*) FROM stix_objects WHERE type = 'relationship' "
                "AND (raw->>'source_ref') = 'indicator--c43a0a05-e8d2-4f64-ae37-3f3fb153f8d9' "
                "AND (raw->>'target_ref') = 'campaign--b549a58c-afd9-4847-85c3-5be13d56d3cc' "
                "AND (raw->>'relationship_type') = 'indicates'",
            ),
        )
    assert n == 2


@pytest.mark.integration
async def test_connector_state_get_set(session_factory) -> None:
    async with session_factory() as session:
        async with session.begin():
            repo = SqlAlchemyConnectorStateRepository(session)
            await repo.set("inst-d", "cursor", {"n": 1})
    async with session_factory() as session2:
        async with session2.begin():
            repo2 = SqlAlchemyConnectorStateRepository(session2)
            value = await repo2.get("inst-d", "cursor")
    assert value == {"n": 1}
