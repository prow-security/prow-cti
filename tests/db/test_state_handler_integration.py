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

"""Integration tests for DB state handlers (Postgres 16)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
import structlog
from sqlalchemy import text

from prow.connector.context import ConnectorContext
from prow.connector.protocol.messages import EmitAckPayload
from prow.connector.transport_inprocess import InProcessTransport
from prow.db.config import DatabaseSettings
from prow.db.session import (
    create_async_engine_from_settings,
    create_async_sessionmaker,
    dispose_engine,
)
from prow.db.state_handler import create_db_state_getter, create_db_state_setter

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
async def test_db_state_set_then_get(session_factory) -> None:
    get_h = create_db_state_getter(session_factory, connector_instance_id="state-inst-a")
    set_h = create_db_state_setter(session_factory, connector_instance_id="state-inst-a")
    await set_h("state-inst-a", "cursor", {"n": 1})
    assert await get_h("state-inst-a", "cursor") == {"n": 1}


@pytest.mark.integration
async def test_db_state_overwrite_same_key(session_factory) -> None:
    get_h = create_db_state_getter(session_factory, connector_instance_id="state-inst-b")
    set_h = create_db_state_setter(session_factory, connector_instance_id="state-inst-b")
    await set_h("state-inst-b", "k", "first")
    await set_h("state-inst-b", "k", "second")
    assert await get_h("state-inst-b", "k") == "second"


@pytest.mark.integration
async def test_db_state_missing_key_returns_none(session_factory) -> None:
    get_h = create_db_state_getter(session_factory, connector_instance_id="state-inst-c")
    assert await get_h("state-inst-c", "no_such_key") is None


@pytest.mark.integration
async def test_db_state_scoped_by_connector_instance_id(session_factory) -> None:
    get_h = create_db_state_getter(session_factory)
    set_h = create_db_state_setter(session_factory)
    await set_h("inst-left", "shared_key", {"side": "left"})
    await set_h("inst-right", "shared_key", {"side": "right"})
    assert await get_h("inst-left", "shared_key") == {"side": "left"}
    assert await get_h("inst-right", "shared_key") == {"side": "right"}


@pytest.mark.integration
async def test_db_state_json_values_round_trip(session_factory) -> None:
    inst = "state-json-inst"
    get_h = create_db_state_getter(session_factory, connector_instance_id=inst)
    set_h = create_db_state_setter(session_factory, connector_instance_id=inst)
    samples: list[tuple[str, object]] = [
        ("s", "hello"),
        ("n", 42),
        ("f", 3.25),
        ("t", True),
        ("fbool", False),
        ("obj", {"a": 1, "nested": None}),
        ("arr", [1, "x", None, {"y": 2}]),
    ]
    for key, val in samples:
        await set_h(inst, key, val)
        assert await get_h(inst, key) == val


@pytest.mark.integration
async def test_ctx_state_through_inprocess_transport_with_db_handlers(session_factory) -> None:
    inst = "ctx-state-inst"
    log = structlog.get_logger("test")

    async def emit_handler(bundle: dict[str, Any]) -> EmitAckPayload:
        del bundle
        return EmitAckPayload(accepted=0, duplicates=0, validation_failures=[])

    get_h = create_db_state_getter(session_factory, connector_instance_id=inst)
    set_h = create_db_state_setter(session_factory, connector_instance_id=inst)
    transport = InProcessTransport(
        inst,
        emit_handler,
        {},
        log,
        meter=None,
        state_get_handler=get_h,
        state_set_handler=set_h,
    )
    ctx = ConnectorContext(transport, {})
    await ctx.set_state("bookmark", {"page": 3})
    assert await ctx.get_state("bookmark") == {"page": 3}
