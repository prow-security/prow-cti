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

"""Unit tests for :class:`prow.connectors.urlhaus.connector.UrlhausConnector`."""

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
from prow.connectors.urlhaus.connector import UrlhausConnector, UrlhausFetchError

_FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "urls_sample.json"
_FIXTURE_BODY = _FIXTURE_PATH.read_bytes()
_N = 3


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

    log = structlog.get_logger("urlhaus-test")
    transport = InProcessTransport("urlhaus-unit", emit_handler, state, log, meter=None)
    ts = (lambda: now) if now is not None else None
    return ConnectorContext(transport, config, time_source=ts)


@pytest.mark.asyncio
async def test_fetch_builds_stix_bundle() -> None:
    captured: list[dict[str, Any]] = []
    state: dict[str, Any] = {}
    fixed = datetime(2026, 5, 16, 12, 0, 0, tzinfo=UTC)
    ctx = _ctx_for_test({}, captured, state, now=fixed)
    client = httpx.AsyncClient(transport=_make_mock_transport(_FIXTURE_BODY))
    conn = UrlhausConnector(ctx)
    conn._http_client_override = client
    try:
        await conn.setup()
        await conn.fetch()
    finally:
        await conn.teardown()
        await client.aclose()

    assert len(captured) == 1
    objs = captured[0]["objects"]
    assert len(objs) == _N * 3
    types = {o["type"] for o in objs}
    assert types == {"url", "indicator", "relationship"}
    assert await ctx.get_state("last_successful_fetch") == fixed.isoformat()


@pytest.mark.asyncio
async def test_fetch_http_error_raises() -> None:
    captured: list[dict[str, Any]] = []
    state: dict[str, Any] = {}
    ctx = _ctx_for_test({}, captured, state)
    client = httpx.AsyncClient(transport=_make_mock_transport(b"", status=401))
    conn = UrlhausConnector(ctx)
    conn._http_client_override = client
    try:
        await conn.setup()
        with pytest.raises(UrlhausFetchError):
            await conn.fetch()
    finally:
        await conn.teardown()
        await client.aclose()
