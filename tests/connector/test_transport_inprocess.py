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

"""Tests for :class:`prow.connector.transport_inprocess.InProcessTransport`."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
import structlog

from prow.connector.protocol.messages import EmitAckPayload, LogLevel, ValidationFailure
from prow.connector.transport_inprocess import InProcessTransport


@pytest.mark.asyncio
async def test_emit_calls_handler_and_returns_ack() -> None:
    captured: list[dict[str, Any]] = []

    async def emit_handler(bundle: dict[str, Any]) -> EmitAckPayload:
        captured.append(bundle)
        return EmitAckPayload(
            accepted=3,
            duplicates=0,
            validation_failures=[
                ValidationFailure(object_id="x", error="y"),
            ],
        )

    log = structlog.get_logger("test")
    transport = InProcessTransport(
        "ci-1",
        emit_handler,
        {},
        log,
        meter=None,
    )
    bundle = {"type": "bundle", "id": "bundle--1", "objects": []}
    ack = await transport.emit(bundle)
    assert captured == [bundle]
    assert ack.accepted == 3
    assert ack.validation_failures[0].object_id == "x"


@pytest.mark.asyncio
async def test_state_round_trip() -> None:
    async def emit_handler(bundle: dict[str, Any]) -> EmitAckPayload:
        del bundle
        return EmitAckPayload(accepted=0, duplicates=0, validation_failures=[])

    state: dict[str, Any] = {}
    log = structlog.get_logger("test")
    transport = InProcessTransport("ci-1", emit_handler, state, log, meter=None)

    await transport.set_state("k", {"v": 1})
    assert await transport.get_state("k") == {"v": 1}
    assert await transport.get_state("missing") is None


@pytest.mark.asyncio
async def test_log_invokes_structlog() -> None:
    log = MagicMock()

    async def emit_handler(bundle: dict[str, Any]) -> EmitAckPayload:
        del bundle
        return EmitAckPayload(accepted=0, duplicates=0, validation_failures=[])

    transport = InProcessTransport("ci-1", emit_handler, {}, log, meter=None)
    await transport.log(LogLevel.INFO, "hello", fields={"foo": "bar"}, exception=None)

    log.info.assert_called_once_with("hello", foo="bar")


@pytest.mark.asyncio
async def test_shutdown_sets_cancelled() -> None:
    async def emit_handler(bundle: dict[str, Any]) -> EmitAckPayload:
        del bundle
        return EmitAckPayload(accepted=0, duplicates=0, validation_failures=[])

    log = structlog.get_logger("test")
    transport = InProcessTransport("ci-1", emit_handler, {}, log, meter=None)

    assert not transport.cancelled.is_set()
    await transport.shutdown()
    assert transport.cancelled.is_set()
