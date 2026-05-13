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

"""Unit tests for :mod:`prow.db.emit_handler` (no Postgres)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import MagicMock

import pytest

from prow.connector.protocol.messages import EmitAckPayload, ValidationFailure
from prow.db.emit_handler import create_db_emit_handler, create_inprocess_db_emit_handler


@pytest.mark.asyncio
async def test_create_db_emit_handler_passes_instance_and_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_ingest(
        session: object,
        bundle: dict[str, Any],
        *,
        source_connector_instance_id: str,
        batch_size: int = 500,
    ) -> EmitAckPayload:
        captured["session"] = session
        captured["bundle"] = bundle
        captured["source"] = source_connector_instance_id
        captured["batch"] = batch_size
        return EmitAckPayload(accepted=2, duplicates=1, validation_failures=[])

    @asynccontextmanager
    async def fake_scope(_sf: object):
        yield "SESSION"

    monkeypatch.setattr("prow.db.emit_handler.ingest_stix_bundle", fake_ingest)
    monkeypatch.setattr("prow.db.emit_handler.session_scope", fake_scope)

    sf = MagicMock(name="session_factory")
    handler = create_db_emit_handler(sf)
    bundle = {"type": "bundle", "id": "bundle--1", "objects": []}
    ack = await handler("connector-inst-7", bundle)
    assert ack == EmitAckPayload(accepted=2, duplicates=1, validation_failures=[])
    assert captured["source"] == "connector-inst-7"
    assert captured["session"] == "SESSION"
    assert captured["bundle"] is bundle


@pytest.mark.asyncio
async def test_create_inprocess_db_emit_handler_fixes_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources: list[str] = []

    async def fake_ingest(
        session: object,
        bundle: dict[str, Any],
        *,
        source_connector_instance_id: str,
        batch_size: int = 500,
    ) -> EmitAckPayload:
        sources.append(source_connector_instance_id)
        return EmitAckPayload(accepted=0, duplicates=0, validation_failures=[])

    @asynccontextmanager
    async def fake_scope(_sf: object):
        yield object()

    monkeypatch.setattr("prow.db.emit_handler.ingest_stix_bundle", fake_ingest)
    monkeypatch.setattr("prow.db.emit_handler.session_scope", fake_scope)

    sf = MagicMock()
    h = create_inprocess_db_emit_handler(sf, connector_instance_id="alpha")
    await h({"type": "bundle", "id": "bundle--2", "objects": []})
    assert sources == ["alpha"]


@pytest.mark.asyncio
async def test_create_db_emit_handler_propagates_validation_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vf = [ValidationFailure(object_id="indicator--x", error="bad")]

    async def fake_ingest(
        session: object,
        bundle: dict[str, Any],
        *,
        source_connector_instance_id: str,
        batch_size: int = 500,
    ) -> EmitAckPayload:
        return EmitAckPayload(accepted=0, duplicates=0, validation_failures=vf)

    @asynccontextmanager
    async def fake_scope(_sf: object):
        yield object()

    monkeypatch.setattr("prow.db.emit_handler.ingest_stix_bundle", fake_ingest)
    monkeypatch.setattr("prow.db.emit_handler.session_scope", fake_scope)

    ack = await create_db_emit_handler(MagicMock())(
        "i", {"type": "bundle", "id": "b", "objects": []}
    )
    assert ack.validation_failures == vf
