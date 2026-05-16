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

"""Unit tests for :class:`prow.connectors.threatfox.connector.ThreatFoxConnector`."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import structlog

from prow.connector.context import ConnectorContext
from prow.connector.protocol.messages import EmitAckPayload
from prow.connector.transport_inprocess import InProcessTransport
from prow.connectors.threatfox.connector import ThreatFoxConnector, ThreatFoxFetchError
from prow.stix.helpers import malware_id

_FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "iocs_sample.json"
_FIXTURE_BODY = _FIXTURE_PATH.read_bytes()
# 5 IOCs: 3 with malware (5 objs), 2 without (3 objs) => 21
_EXPECTED_OBJECTS = 21


def _make_mock_transport(body: bytes, status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=body)

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

    log = structlog.get_logger("threatfox-test")
    transport = InProcessTransport("threatfox-unit", emit_handler, state, log, meter=None)
    ts = (lambda: now) if now is not None else None
    return ConnectorContext(transport, config, time_source=ts)


@pytest.mark.asyncio
async def test_fetch_first_run_uses_days_back() -> None:
    captured: list[dict[str, Any]] = []
    state: dict[str, Any] = {}
    fixed = datetime(2026, 5, 16, 12, 0, 0, tzinfo=UTC)
    ctx = _ctx_for_test({"days_back": 7}, captured, state, now=fixed)
    seen_days: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content.decode())
        seen_days.append(body["days"])
        return httpx.Response(200, content=_FIXTURE_BODY)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    conn = ThreatFoxConnector(ctx)
    conn._http_client_override = client
    try:
        await conn.setup()
        await conn.fetch()
    finally:
        await conn.teardown()
        await client.aclose()

    assert seen_days == [7]
    assert len(captured) == 1
    assert len(captured[0]["objects"]) == _EXPECTED_OBJECTS
    assert await ctx.get_state("last_fetch_date") == "2026-05-16"


@pytest.mark.asyncio
async def test_fetch_incremental_uses_one_day() -> None:
    captured: list[dict[str, Any]] = []
    state: dict[str, Any] = {"last_fetch_date": "2026-05-15"}
    ctx = _ctx_for_test({}, captured, state)
    seen_days: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content.decode())
        seen_days.append(body["days"])
        return httpx.Response(200, content=_FIXTURE_BODY)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    conn = ThreatFoxConnector(ctx)
    conn._http_client_override = client
    try:
        await conn.setup()
        await conn.fetch()
    finally:
        await conn.teardown()
        await client.aclose()

    assert seen_days == [1]


@pytest.mark.asyncio
async def test_fetch_no_results_sets_state() -> None:
    captured: list[dict[str, Any]] = []
    state: dict[str, Any] = {}
    fixed = datetime(2026, 5, 16, 12, 0, 0, tzinfo=UTC)
    ctx = _ctx_for_test({}, captured, state, now=fixed)
    body = b'{"query_status": "no_results", "data": []}'
    client = httpx.AsyncClient(transport=_make_mock_transport(body))
    conn = ThreatFoxConnector(ctx)
    conn._http_client_override = client
    try:
        await conn.setup()
        await conn.fetch()
    finally:
        await conn.teardown()
        await client.aclose()

    assert captured == []
    assert await ctx.get_state("last_fetch_date") == "2026-05-16"


def _malware_objects(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    return [o for o in bundle["objects"] if o.get("type") == "malware"]


@pytest.mark.asyncio
async def test_fetch_malware_ids_are_deterministic() -> None:
    captured: list[dict[str, Any]] = []
    state: dict[str, Any] = {}
    ctx = _ctx_for_test({}, captured, state)
    client = httpx.AsyncClient(transport=_make_mock_transport(_FIXTURE_BODY))
    conn = ThreatFoxConnector(ctx)
    conn._http_client_override = client
    try:
        await conn.setup()
        await conn.fetch()
        await conn.fetch()
    finally:
        await conn.teardown()
        await client.aclose()

    assert len(captured) == 2
    first_ids = {o["id"] for o in _malware_objects(captured[0])}
    second_ids = {o["id"] for o in _malware_objects(captured[1])}
    assert first_ids == second_ids
    assert malware_id("Cobalt Strike") in first_ids
    assert malware_id("Emotet") in first_ids
    assert malware_id("AgentTesla") in first_ids


@pytest.mark.asyncio
async def test_fetch_http_error_raises() -> None:
    captured: list[dict[str, Any]] = []
    state: dict[str, Any] = {}
    ctx = _ctx_for_test({}, captured, state)
    client = httpx.AsyncClient(transport=_make_mock_transport(b"", status=401))
    conn = ThreatFoxConnector(ctx)
    conn._http_client_override = client
    try:
        await conn.setup()
        with pytest.raises(ThreatFoxFetchError):
            await conn.fetch()
    finally:
        await conn.teardown()
        await client.aclose()
