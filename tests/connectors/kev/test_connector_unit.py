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

"""Unit tests for :class:`prow.connectors.kev.connector.KevConnector` (no network)."""

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
from prow.connectors.kev.connector import KevConnector, KevFeedFormatError, KevFetchError

_FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "kev_sample.json"
_FIXTURE_BODY = _FIXTURE_PATH.read_bytes()
_N = 4  # CVE rows in kev_sample.json


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

    log = structlog.get_logger("kev-test")
    transport = InProcessTransport("kev-unit", emit_handler, state, log, meter=None)
    ts = (lambda: now) if now is not None else None
    return ConnectorContext(transport, config, time_source=ts)


@pytest.mark.asyncio
async def test_setup_builds_cisa_identity() -> None:
    captured: list[dict[str, Any]] = []
    state: dict[str, Any] = {}
    fixed = datetime(2026, 5, 13, 12, 0, 0, tzinfo=UTC)
    ctx = _ctx_for_test({"feed_url": "http://example.invalid/kev.json"}, captured, state, now=fixed)
    conn = KevConnector(ctx)
    await conn.setup()
    ident = conn._identity
    assert ident is not None
    assert ident.name == "Cybersecurity and Infrastructure Security Agency"
    assert ident.identity_class == "organization"
    await conn.teardown()


@pytest.mark.asyncio
async def test_fetch_200_builds_bundle_and_state() -> None:
    captured: list[dict[str, Any]] = []
    state: dict[str, Any] = {}
    fixed = datetime(2026, 5, 13, 15, 30, 0, tzinfo=UTC)
    ctx = _ctx_for_test(
        {"feed_url": "http://example.invalid/kev.json", "http_timeout_seconds": 5.0},
        captured,
        state,
        now=fixed,
    )
    transport = _make_mock_transport(
        200,
        _FIXTURE_BODY,
        {"ETag": 'W/"kev-1"', "Last-Modified": "Wed, 13 May 2026 17:58:37 GMT"},
    )
    client = httpx.AsyncClient(transport=transport)
    conn = KevConnector(ctx)
    conn._http_client_override = client
    try:
        await conn.setup()
        await conn.fetch()
    finally:
        await conn.teardown()
        await client.aclose()

    assert len(captured) == 1
    bundle = captured[0]
    assert bundle["type"] == "bundle"
    objs = bundle["objects"]
    assert len(objs) == 1 + 3 * _N

    assert objs[0]["type"] == "identity"

    by_cve: dict[str, dict[str, Any]] = {}
    for i in range(_N):
        base = 1 + i * 3
        v, ind, rel = objs[base], objs[base + 1], objs[base + 2]
        assert v["type"] == "vulnerability"
        assert ind["type"] == "indicator"
        assert rel["type"] == "relationship"
        cve = v["name"]
        assert isinstance(cve, str)
        by_cve[cve] = {"v": v, "ind": ind, "rel": rel}

    cve0 = "CVE-2026-42208"
    row = by_cve[cve0]["v"]
    assert row["description"].startswith("BerriAI LiteLLM contains a SQL injection")
    assert row["x_kev_due_date"] == "2026-05-11"
    assert "Apply mitigations per vendor" in row["x_kev_required_action"]
    assert row["x_kev_known_ransomware_use"] == "Unknown"
    refs = row["external_references"]
    assert any(
        r.get("external_id") == cve0 and "cve.org/CVERecord" in (r.get("url") or "") for r in refs
    )

    ind0 = by_cve[cve0]["ind"]
    assert ind0["name"] == f"KEV: {cve0}"
    assert ind0["pattern"] == f"[vulnerability:name = '{cve0}']"
    assert ind0["valid_from"] == "2026-05-08T00:00:00.000Z"
    assert ind0["confidence"] == 100

    rel0 = by_cve[cve0]["rel"]
    assert rel0["relationship_type"] == "indicates"
    assert rel0["source_ref"] == ind0["id"]
    assert rel0["target_ref"] == row["id"]

    assert await ctx.get_state("etag") == 'W/"kev-1"'
    assert await ctx.get_state("last_modified") == "Wed, 13 May 2026 17:58:37 GMT"
    assert await ctx.get_state("last_successful_fetch") == fixed.isoformat()


@pytest.mark.asyncio
async def test_fetch_304_emits_nothing() -> None:
    captured: list[dict[str, Any]] = []
    state: dict[str, Any] = {}
    ctx = _ctx_for_test({"feed_url": "http://example.invalid/kev.json"}, captured, state)

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                200,
                content=_FIXTURE_BODY,
                headers={"ETag": 'W/"roundtrip"'},
            )
        assert request.headers.get("if-none-match") == 'W/"roundtrip"'
        return httpx.Response(304, headers={})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    conn = KevConnector(ctx)
    conn._http_client_override = client
    try:
        await conn.setup()
        await conn.fetch()
        await conn.fetch()
    finally:
        await conn.teardown()
        await client.aclose()

    assert len(captured) == 1


@pytest.mark.asyncio
async def test_fetch_http_500_raises_and_skips_state() -> None:
    captured: list[dict[str, Any]] = []
    state: dict[str, Any] = {}
    ctx = _ctx_for_test({"feed_url": "http://example.invalid/kev.json"}, captured, state)
    transport = _make_mock_transport(500, b"error", {})
    client = httpx.AsyncClient(transport=transport)
    conn = KevConnector(ctx)
    conn._http_client_override = client
    try:
        await conn.setup()
        with pytest.raises(KevFetchError):
            await conn.fetch()
    finally:
        await conn.teardown()
        await client.aclose()

    assert captured == []
    assert await ctx.get_state("etag") is None
    assert await ctx.get_state("last_successful_fetch") is None


@pytest.mark.asyncio
async def test_fetch_invalid_json_raises() -> None:
    captured: list[dict[str, Any]] = []
    state: dict[str, Any] = {}
    ctx = _ctx_for_test({"feed_url": "http://example.invalid/kev.json"}, captured, state)
    transport = _make_mock_transport(200, b"not-json-at-all", {})
    client = httpx.AsyncClient(transport=transport)
    conn = KevConnector(ctx)
    conn._http_client_override = client
    try:
        await conn.setup()
        with pytest.raises(KevFeedFormatError):
            await conn.fetch()
    finally:
        await conn.teardown()
        await client.aclose()

    assert captured == []


@pytest.mark.asyncio
async def test_fetch_missing_vulnerabilities_raises() -> None:
    captured: list[dict[str, Any]] = []
    state: dict[str, Any] = {}
    ctx = _ctx_for_test({"feed_url": "http://example.invalid/kev.json"}, captured, state)
    transport = _make_mock_transport(200, b'{"count": 0}', {})
    client = httpx.AsyncClient(transport=transport)
    conn = KevConnector(ctx)
    conn._http_client_override = client
    try:
        await conn.setup()
        with pytest.raises(KevFeedFormatError):
            await conn.fetch()
    finally:
        await conn.teardown()
        await client.aclose()
