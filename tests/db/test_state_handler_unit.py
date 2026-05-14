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

"""Unit tests for :mod:`prow.db.state_handler` (no Postgres)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from prow.db.state_handler import create_db_state_getter, create_db_state_setter


@pytest.mark.asyncio
async def test_create_db_state_getter_uses_session_and_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeRepo:
        def __init__(self, session: object) -> None:
            captured["session"] = session

        async def get(self, instance_id: str, key: str) -> Any:
            captured["instance_id"] = instance_id
            captured["key"] = key
            return {"x": 1}

    @asynccontextmanager
    async def fake_scope(_sf: object):
        yield "SESSION"

    monkeypatch.setattr("prow.db.state_handler.session_scope", fake_scope)
    monkeypatch.setattr("prow.db.state_handler.SqlAlchemyConnectorStateRepository", FakeRepo)

    sf = MagicMock(name="session_factory")
    getter = create_db_state_getter(sf)
    value = await getter("connector-z", "my-key")
    assert value == {"x": 1}
    assert captured["session"] == "SESSION"
    assert captured["instance_id"] == "connector-z"
    assert captured["key"] == "my-key"


@pytest.mark.asyncio
async def test_create_db_state_getter_fixed_instance_id_ignores_arg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    class FakeRepo:
        def __init__(self, _session: object) -> None:
            pass

        async def get(self, instance_id: str, key: str) -> Any:
            seen.append(instance_id)
            return key

    @asynccontextmanager
    async def fake_scope(_sf: object):
        yield object()

    monkeypatch.setattr("prow.db.state_handler.session_scope", fake_scope)
    monkeypatch.setattr("prow.db.state_handler.SqlAlchemyConnectorStateRepository", FakeRepo)

    getter = create_db_state_getter(MagicMock(), connector_instance_id="fixed")
    await getter("ignored", "k")
    assert seen == ["fixed"]


@pytest.mark.asyncio
async def test_create_db_state_setter_commits_via_begin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeRepo:
        def __init__(self, session: object) -> None:
            captured["session"] = session

        async def set(self, instance_id: str, key: str, value: Any) -> None:
            captured["set_args"] = (instance_id, key, value)

    session_obj = MagicMock()
    begin_ctx = MagicMock()
    begin_ctx.__aenter__ = AsyncMock(return_value=None)
    begin_ctx.__aexit__ = AsyncMock(return_value=None)
    session_obj.begin = MagicMock(return_value=begin_ctx)

    @asynccontextmanager
    async def fake_scope(_sf: object):
        yield session_obj

    monkeypatch.setattr("prow.db.state_handler.session_scope", fake_scope)
    monkeypatch.setattr("prow.db.state_handler.SqlAlchemyConnectorStateRepository", FakeRepo)

    sf = MagicMock()
    setter = create_db_state_setter(sf)
    await setter("inst-1", "cursor", {"n": 2})
    session_obj.begin.assert_called_once()
    assert captured["set_args"] == ("inst-1", "cursor", {"n": 2})


@pytest.mark.asyncio
async def test_create_db_state_setter_fixed_instance_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeRepo:
        def __init__(self, _session: object) -> None:
            pass

        async def set(self, instance_id: str, key: str, value: Any) -> None:
            captured["set_args"] = (instance_id, key, value)

    session_obj = MagicMock()
    begin_ctx = MagicMock()
    begin_ctx.__aenter__ = AsyncMock(return_value=None)
    begin_ctx.__aexit__ = AsyncMock(return_value=None)
    session_obj.begin = MagicMock(return_value=begin_ctx)

    @asynccontextmanager
    async def fake_scope(_sf: object):
        yield session_obj

    monkeypatch.setattr("prow.db.state_handler.session_scope", fake_scope)
    monkeypatch.setattr("prow.db.state_handler.SqlAlchemyConnectorStateRepository", FakeRepo)

    setter = create_db_state_setter(MagicMock(), connector_instance_id="pinned")
    await setter("ignored", "k", 3)
    assert captured["set_args"] == ("pinned", "k", 3)
