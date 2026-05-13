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

"""Integration tests for DB emit handlers (Postgres 16)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text

from prow.connector.context import ConnectorContext
from prow.connector.transport_inprocess import InProcessTransport
from prow.db.config import DatabaseSettings
from prow.db.emit_handler import create_db_emit_handler, create_inprocess_db_emit_handler
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
async def session_factory(pg_engine):
    return create_async_sessionmaker(pg_engine)


@pytest_asyncio.fixture(autouse=True, scope="function", loop_scope="module")
async def truncate_tables(pg_engine):
    async with pg_engine.begin() as conn:
        await conn.execute(
            text("TRUNCATE TABLE stix_objects, connector_state RESTART IDENTITY CASCADE"),
        )
    yield


@pytest.mark.integration
async def test_db_emit_handler_persists_and_counts_duplicates(session_factory) -> None:
    bundle = {
        "type": "bundle",
        "id": "bundle--emit-handler-1",
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
    emit = create_db_emit_handler(session_factory)
    first = await emit("emit-handler-inst", bundle)
    assert first.accepted == 1
    assert first.duplicates == 0
    assert first.validation_failures == []

    second = await emit("emit-handler-inst", bundle)
    assert second.accepted == 0
    assert second.duplicates == 1


@pytest.mark.integration
async def test_db_emit_handler_mixed_valid_invalid(session_factory) -> None:
    good = {
        "type": "indicator",
        "spec_version": "2.1",
        "id": "indicator--aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "created": "2024-01-01T12:00:00.000Z",
        "modified": "2024-01-01T12:00:00.000Z",
        "pattern": "[ipv4-addr:value = '198.51.100.7']",
        "pattern_type": "stix",
        "valid_from": "2024-01-01T12:00:00.000Z",
    }
    bad = {"type": "indicator", "id": "indicator--missing-fields"}
    bundle = {
        "type": "bundle",
        "id": "bundle--emit-handler-mixed",
        "objects": [good, bad],
    }
    emit = create_db_emit_handler(session_factory)
    ack = await emit("emit-handler-inst", bundle)
    assert ack.accepted == 1
    assert ack.duplicates == 0
    assert ack.validation_failures


@pytest.mark.integration
async def test_inprocess_emit_through_connector_context(session_factory) -> None:
    bundle = {
        "type": "bundle",
        "id": "bundle--ctx-emit-1",
        "objects": [
            {
                "type": "indicator",
                "spec_version": "2.1",
                "id": "indicator--bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                "created": "2024-01-01T12:00:00.000Z",
                "modified": "2024-01-01T12:00:00.000Z",
                "pattern": "[ipv4-addr:value = '198.51.100.8']",
                "pattern_type": "stix",
                "valid_from": "2024-01-01T12:00:00.000Z",
            },
        ],
    }
    import structlog

    log = structlog.get_logger("test")
    transport = InProcessTransport(
        "ctx-emit-inst",
        create_inprocess_db_emit_handler(session_factory, connector_instance_id="ctx-emit-inst"),
        {},
        log,
        meter=None,
    )
    ctx = ConnectorContext(transport, {})
    result = await ctx.emit(bundle)
    assert result.accepted == 1
    assert result.duplicates == 0
    assert not result.failures


@pytest.mark.integration
async def test_db_emit_handler_two_relationships_same_triple(session_factory, pg_engine) -> None:
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
        "id": "bundle--emit-handler-rel",
        "objects": [campaign, indicator, rel1, rel2],
    }
    emit = create_db_emit_handler(session_factory)
    ack = await emit("emit-rel-inst", bundle)
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
