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

"""Tests for :class:`prow.connector.context.ConnectorContext`."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
import structlog

from prow.connector.context import ConnectorContext
from prow.connector.protocol.messages import EmitAckPayload, LogLevel
from prow.connector.transport_inprocess import InProcessTransport
from prow.stix.helpers import bundle as make_bundle
from prow.stix.helpers import indicator


@pytest.mark.asyncio
async def test_emit_bundle_model_dump_round_trip() -> None:
    bundles_in: list[dict[str, Any]] = []

    async def emit_handler(raw: dict[str, Any]) -> EmitAckPayload:
        bundles_in.append(raw)
        return EmitAckPayload(accepted=1, duplicates=0, validation_failures=[])

    log = structlog.get_logger("ctx-test")
    transport = InProcessTransport("inst-a", emit_handler, {}, log, meter=None)
    ctx = ConnectorContext(transport, {"region": "eu"})

    ind = indicator(
        name="x",
        pattern="[ipv4-addr:value = '192.0.2.1']",
        pattern_type="stix",
        confidence=50,
        indicator_types=["malicious-activity"],
    )
    b = make_bundle([ind])
    result = await ctx.emit(b)
    assert result.accepted == 1
    assert bundles_in[0]["type"] == "bundle"
    assert bundles_in[0]["objects"]


@pytest.mark.asyncio
async def test_emit_raw_dict() -> None:
    captured: list[dict[str, Any]] = []

    async def emit_handler(raw: dict[str, Any]) -> EmitAckPayload:
        captured.append(raw)
        return EmitAckPayload(accepted=0, duplicates=0, validation_failures=[])

    log = structlog.get_logger("ctx-test")
    transport = InProcessTransport("inst-a", emit_handler, {}, log, meter=None)
    ctx = ConnectorContext(transport, {})

    raw = {"type": "bundle", "id": "bundle--z", "objects": []}
    await ctx.emit(raw)
    assert captured[0] == raw


@pytest.mark.asyncio
async def test_log_routes_through_transport() -> None:
    captured: list[tuple[Any, str, dict[str, Any] | None, str | None]] = []

    async def emit_handler(raw: dict[str, Any]) -> EmitAckPayload:
        del raw
        return EmitAckPayload(accepted=0, duplicates=0, validation_failures=[])

    log = structlog.get_logger("ctx-test")
    transport = InProcessTransport("inst-log", emit_handler, {}, log, meter=None)

    async def capture_log(
        level: LogLevel,
        message: str,
        fields: dict[str, Any] | None = None,
        exception: str | None = None,
    ) -> None:
        captured.append((level, message, fields, exception))

    transport.log = capture_log  # type: ignore[method-assign]

    ctx = ConnectorContext(transport, {})
    ctx.log.info("hello", foo="bar")
    await asyncio.sleep(0)

    assert len(captured) == 1
    level, message, fields, exc = captured[0]
    assert level is LogLevel.INFO
    assert message == "hello"
    assert exc is None
    assert fields is not None
    assert fields["foo"] == "bar"
    assert fields["connector_instance_id"] == "inst-log"


@pytest.mark.asyncio
async def test_last_run_at_from_state_store() -> None:
    async def emit_handler(raw: dict[str, Any]) -> EmitAckPayload:
        del raw
        return EmitAckPayload(accepted=0, duplicates=0, validation_failures=[])

    log = structlog.get_logger("ctx-test")
    past = datetime(2026, 1, 2, tzinfo=UTC)
    state = {"__last_run_at__": past.isoformat()}
    transport = InProcessTransport("inst-a", emit_handler, state, log, meter=None)
    ctx = ConnectorContext(transport, {})
    assert ctx.last_run_at == past


@pytest.mark.asyncio
async def test_now_uses_time_source() -> None:
    async def emit_handler(raw: dict[str, Any]) -> EmitAckPayload:
        del raw
        return EmitAckPayload(accepted=0, duplicates=0, validation_failures=[])

    log = structlog.get_logger("ctx-test")
    transport = InProcessTransport("inst-a", emit_handler, {}, log, meter=None)
    fixed = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
    ctx = ConnectorContext(transport, {}, time_source=lambda: fixed)
    assert ctx.now == fixed


@pytest.mark.asyncio
async def test_cancelled_same_as_transport() -> None:
    async def emit_handler(raw: dict[str, Any]) -> EmitAckPayload:
        del raw
        return EmitAckPayload(accepted=0, duplicates=0, validation_failures=[])

    log = structlog.get_logger("ctx-test")
    transport = InProcessTransport("inst-a", emit_handler, {}, log, meter=None)
    ctx = ConnectorContext(transport, {})
    assert ctx.cancelled is transport.cancelled
