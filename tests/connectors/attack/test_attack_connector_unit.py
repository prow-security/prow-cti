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

"""Unit tests for :class:`prow.connectors.attack.connector.AttackConnector`."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import structlog

from prow.connector.context import ConnectorContext
from prow.connector.dev_emit import DevEmitHandler
from prow.connector.protocol.messages import EmitAckPayload
from prow.connector.transport_inprocess import InProcessTransport
from prow.connectors.attack.connector import (
    AttackConnector,
    AttackFeedFormatError,
    AttackFetchError,
)

_FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "attack_sample.json"
_FIXTURE_BODY = _FIXTURE_PATH.read_bytes()
# Six course-of-action plus two x-mitre-* custom types from the MITRE bundle sample.
_EXPECTED_OBJECTS = 8


def _make_mock_transport(
    response_status: int,
    response_body: bytes,
    headers: dict[str, str],
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(response_status, content=response_body, headers=headers)

    return httpx.MockTransport(handler)


def _ctx_for_test(
    config: dict[str, Any],
    captured: list[dict[str, Any]],
    state: dict[str, Any],
    *,
    now: datetime | None = None,
) -> ConnectorContext:
    async def emit_handler(bundle: dict[str, Any]) -> EmitAckPayload:
        captured.append(bundle)
        return EmitAckPayload(accepted=99, duplicates=0, validation_failures=[])

    log = structlog.get_logger("attack-test")
    transport = InProcessTransport("attack-unit", emit_handler, state, log, meter=None)
    ts = (lambda: now) if now is not None else None
    return ConnectorContext(transport, config, time_source=ts)


@pytest.mark.asyncio
async def test_fetch_emits_validated_objects_and_state() -> None:
    captured: list[dict[str, Any]] = []
    state: dict[str, Any] = {}
    fixed = datetime(2026, 5, 16, 12, 0, 0, tzinfo=UTC)
    ctx = _ctx_for_test(
        {"stix_url": "http://example.invalid/attack.json"},
        captured,
        state,
        now=fixed,
    )
    transport = _make_mock_transport(
        200,
        _FIXTURE_BODY,
        {"ETag": 'W/"attack-1"', "Last-Modified": "Fri, 16 May 2026 12:00:00 GMT"},
    )
    client = httpx.AsyncClient(transport=transport)
    conn = AttackConnector(ctx)
    conn._http_client_override = client
    try:
        await conn.setup()
        await conn.fetch()
    finally:
        await conn.teardown()
        await client.aclose()

    assert len(captured) == 1
    objs = captured[0]["objects"]
    assert len(objs) == _EXPECTED_OBJECTS
    types = {o["type"] for o in objs}
    assert types == {"course-of-action", "x-mitre-tactic", "x-mitre-matrix"}
    assert await ctx.get_state("etag") == 'W/"attack-1"'
    assert await ctx.get_state("last_successful_fetch") == fixed.isoformat()


@pytest.mark.asyncio
async def test_fetch_304_not_modified() -> None:
    captured: list[dict[str, Any]] = []
    state: dict[str, Any] = {"etag": 'W/"attack-1"'}
    ctx = _ctx_for_test({"stix_url": "http://example.invalid/attack.json"}, captured, state)
    transport = _make_mock_transport(304, b"", {})
    client = httpx.AsyncClient(transport=transport)
    conn = AttackConnector(ctx)
    conn._http_client_override = client
    try:
        await conn.setup()
        await conn.fetch()
    finally:
        await conn.teardown()
        await client.aclose()
    assert captured == []


@pytest.mark.asyncio
async def test_fetch_file_url() -> None:
    captured: list[dict[str, Any]] = []
    state: dict[str, Any] = {}
    ctx = _ctx_for_test({"stix_url": _FIXTURE_PATH.as_uri()}, captured, state)
    conn = AttackConnector(ctx)
    await conn.setup()
    await conn.fetch()
    await conn.teardown()
    assert sum(len(b["objects"]) for b in captured) == _EXPECTED_OBJECTS


@pytest.mark.asyncio
async def test_fetch_http_error_raises() -> None:
    captured: list[dict[str, Any]] = []
    state: dict[str, Any] = {}
    ctx = _ctx_for_test({"stix_url": "http://example.invalid/attack.json"}, captured, state)
    transport = _make_mock_transport(503, b"unavailable", {})
    client = httpx.AsyncClient(transport=transport)
    conn = AttackConnector(ctx)
    conn._http_client_override = client
    try:
        await conn.setup()
        with pytest.raises(AttackFetchError):
            await conn.fetch()
    finally:
        await conn.teardown()
        await client.aclose()


@pytest.mark.asyncio
async def test_fetch_emits_x_mitre_types_through_dev_emit_handler() -> None:
    captured: list[dict[str, Any]] = []
    state: dict[str, Any] = {}

    async def capture(bundle: dict[str, Any]) -> EmitAckPayload:
        captured.append(bundle)
        return EmitAckPayload(accepted=0, duplicates=0, validation_failures=[])

    log = structlog.get_logger("attack-emit-test")
    transport = InProcessTransport("attack-emit", capture, state, log, meter=None)
    ctx = ConnectorContext(transport, {"stix_url": _FIXTURE_PATH.as_uri()})
    dev_emit = DevEmitHandler(allow_custom_types=True)

    conn = AttackConnector(ctx)
    await conn.setup()
    await conn.fetch()
    await conn.teardown()

    assert len(captured) == 1
    ack = await dev_emit("mitre-attack", captured[0])
    assert ack.accepted == _EXPECTED_OBJECTS
    assert not ack.validation_failures
    x_mitre = [o for o in captured[0]["objects"] if str(o.get("type", "")).startswith("x-mitre-")]
    assert len(x_mitre) == 2


@pytest.mark.asyncio
async def test_fetch_invalid_json_raises() -> None:
    captured: list[dict[str, Any]] = []
    state: dict[str, Any] = {}
    ctx = _ctx_for_test({"stix_url": "http://example.invalid/attack.json"}, captured, state)
    transport = _make_mock_transport(200, b"not-json", {})
    client = httpx.AsyncClient(transport=transport)
    conn = AttackConnector(ctx)
    conn._http_client_override = client
    try:
        await conn.setup()
        with pytest.raises(AttackFeedFormatError):
            await conn.fetch()
    finally:
        await conn.teardown()
        await client.aclose()
