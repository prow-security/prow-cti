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

import os
import subprocess
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from prow.api.app import app
from prow.api.deps import get_db_session
from prow.db.config import DatabaseSettings
from prow.db.repositories import SqlAlchemyStixObjectRepository
from prow.db.session import (
    create_async_engine_from_settings,
    create_async_sessionmaker,
    dispose_engine,
)

pytestmark = pytest.mark.asyncio(loop_scope="module")

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


@pytest_asyncio.fixture(scope="module", loop_scope="module")
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


@pytest_asyncio.fixture(scope="function", loop_scope="module")
async def pg_session(pg_engine):
    session_factory = create_async_sessionmaker(pg_engine)
    session = session_factory()
    yield session
    await session.close()


@pytest_asyncio.fixture(autouse=True, scope="function", loop_scope="module")
async def truncate_tables(pg_engine):
    async with pg_engine.begin() as conn:
        await conn.execute(
            text("TRUNCATE TABLE stix_objects, connector_state RESTART IDENTITY CASCADE"),
        )
    yield


@pytest.fixture
async def seeded_db(pg_session):
    repo = SqlAlchemyStixObjectRepository(pg_session)

    objects = [
        {
            "type": "indicator",
            "spec_version": "2.1",
            "id": "indicator--1",
            "created": "2026-05-13T22:04:04.000Z",
            "modified": "2026-05-13T22:04:04.000Z",
            "pattern": "[ipv4-addr:value = '1.2.3.4']",
            "pattern_type": "stix",
            "valid_from": "2026-05-13T22:04:04.000Z",
            "name": "Test Indicator",
        },
        {
            "type": "indicator",
            "spec_version": "2.1",
            "id": "indicator--2",
            "created": "2026-05-13T22:04:04.000Z",
            "modified": "2026-05-13T22:04:04.000Z",
            "pattern": "[ipv4-addr:value = '5.6.7.8']",
            "pattern_type": "stix",
            "valid_from": "2026-05-13T22:04:04.000Z",
            "name": "Test Indicator 2",
        },
        {
            "type": "vulnerability",
            "spec_version": "2.1",
            "id": "vulnerability--1",
            "created": "2026-05-13T22:04:04.000Z",
            "modified": "2026-05-13T22:04:04.000Z",
            "name": "CVE-2024-12345",
            "description": "A test vulnerability",
        },
        {
            "type": "ipv4-addr",
            "spec_version": "2.1",
            "id": "ipv4-addr--1",
            "value": "1.2.3.4",
        },
        {
            "type": "relationship",
            "spec_version": "2.1",
            "id": "relationship--1",
            "created": "2026-05-13T22:04:04.000Z",
            "modified": "2026-05-13T22:04:04.000Z",
            "relationship_type": "indicates",
            "source_ref": "indicator--1",
            "target_ref": "vulnerability--1",
        },
    ]

    await repo.bulk_insert_dedupe(objects, source_connector_instance_id="test")
    await pg_session.commit()
    return pg_session


@pytest.fixture
def client(seeded_db):
    async def override_get_db_session():
        yield seeded_db

    app.dependency_overrides[get_db_session] = override_get_db_session
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.slow
@pytest.mark.asyncio
async def test_list_objects(client):
    response = await client.get("/api/v1/objects")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 5
    assert len(data["objects"]) == 5


@pytest.mark.slow
@pytest.mark.asyncio
async def test_list_objects_by_type(client):
    response = await client.get("/api/v1/objects?type=indicator")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert len(data["objects"]) == 2
    assert all(obj["type"] == "indicator" for obj in data["objects"])


@pytest.mark.slow
@pytest.mark.asyncio
async def test_get_object(client):
    response = await client.get("/api/v1/objects/indicator--1")
    assert response.status_code == 200
    data = response.json()
    assert data["object"]["id"] == "indicator--1"


@pytest.mark.slow
@pytest.mark.asyncio
async def test_get_object_not_found(client):
    response = await client.get("/api/v1/objects/indicator--nonexistent")
    assert response.status_code == 404
    assert response.json() == {"detail": "Object not found", "id": "indicator--nonexistent"}


@pytest.mark.slow
@pytest.mark.asyncio
async def test_search_objects(client):
    response = await client.get("/api/v1/search?q=CVE-2024-12345")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["objects"][0]["id"] == "vulnerability--1"


@pytest.mark.slow
@pytest.mark.asyncio
async def test_get_object_relationships(client):
    response = await client.get("/api/v1/objects/indicator--1/relationships")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["relationships"][0]["id"] == "relationship--1"


@pytest.mark.slow
@pytest.mark.asyncio
async def test_pagination(client):
    response1 = await client.get("/api/v1/objects?limit=2&offset=0")
    assert response1.status_code == 200
    data1 = response1.json()
    assert len(data1["objects"]) == 2

    response2 = await client.get("/api/v1/objects?limit=2&offset=2")
    assert response2.status_code == 200
    data2 = response2.json()
    assert len(data2["objects"]) == 2

    # Ensure they are different objects
    ids1 = {obj["id"] for obj in data1["objects"]}
    ids2 = {obj["id"] for obj in data2["objects"]}
    assert not ids1.intersection(ids2)


@pytest.mark.slow
@pytest.mark.asyncio
async def test_ingest_stats(client):
    response = await client.get("/api/v1/ingest/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["total_objects"] == 5
    assert data["by_type"]["indicator"] == 2
    assert data["by_type"]["vulnerability"] == 1
    assert data["by_type"]["ipv4-addr"] == 1
    assert data["by_type"]["relationship"] == 1
    assert data["last_ingested_at"] is not None
