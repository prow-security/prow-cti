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

"""Tests for connector protocol message models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from prow.connector.protocol.messages import (
    CancelAckPayload,
    CancelPayload,
    EmitAckPayload,
    EmitPayload,
    Envelope,
    GetStateAckPayload,
    GetStatePayload,
    HealthAckPayload,
    HealthPayload,
    HealthStatus,
    HelloAckPayload,
    HelloPayload,
    LogLevel,
    LogPayload,
    MetricPayload,
    SetStateAckPayload,
    SetStatePayload,
    ShutdownAckPayload,
    ShutdownPayload,
    ValidationFailure,
)

PAYLOAD_CASES: dict[str, BaseModel] = {
    "hello": HelloPayload(
        runtime_version="0.0.0",
        supported_protocol_versions=[1],
        config={"api_key": "secret"},
    ),
    "hello-ack": HelloAckPayload(connector_version="1.2.3", protocol_version=1),
    "shutdown": ShutdownPayload(grace_period_seconds=30),
    "shutdown-ack": ShutdownAckPayload(),
    "emit": EmitPayload(bundle={"type": "bundle", "id": "bundle--1", "objects": []}),
    "emit-ack": EmitAckPayload(
        accepted=1,
        duplicates=0,
        validation_failures=[ValidationFailure(object_id="indicator--1", error="bad")],
    ),
    "log": LogPayload(
        level=LogLevel.INFO,
        message="ready",
        timestamp=datetime(2026, 5, 7, tzinfo=UTC),
        fields={"connector": "demo"},
        exception=None,
    ),
    "metric": MetricPayload(
        name="objects",
        value=3.0,
        unit="count",
        tags={"kind": "indicator"},
        timestamp=datetime(2026, 5, 7, tzinfo=UTC),
    ),
    "set-state": SetStatePayload(key="cursor", value={"page": 2}),
    "set-state-ack": SetStateAckPayload(),
    "get-state": GetStatePayload(key="cursor"),
    "get-state-ack": GetStateAckPayload(value={"page": 2}),
    "health": HealthPayload(),
    "health-ack": HealthAckPayload(status=HealthStatus.HEALTHY),
    "cancel": CancelPayload(target_id="operation-1"),
    "cancel-ack": CancelAckPayload(cancelled=True),
}


@pytest.mark.parametrize("payload", PAYLOAD_CASES.values(), ids=PAYLOAD_CASES.keys())
def test_payload_models_round_trip(payload: BaseModel) -> None:
    payload_type = type(payload)
    parsed = payload_type.model_validate_json(payload.model_dump_json())

    assert parsed == payload


def test_all_message_kinds_have_payload_models() -> None:
    assert set(PAYLOAD_CASES) == {
        "hello",
        "hello-ack",
        "shutdown",
        "shutdown-ack",
        "emit",
        "emit-ack",
        "log",
        "metric",
        "set-state",
        "set-state-ack",
        "get-state",
        "get-state-ack",
        "health",
        "health-ack",
        "cancel",
        "cancel-ack",
    }


@pytest.mark.parametrize("kind,payload", PAYLOAD_CASES.items())
def test_envelope_accepts_each_message_kind(kind: str, payload: BaseModel) -> None:
    envelope = Envelope(v=1, id="message-1", kind=kind, payload=payload.model_dump())

    assert envelope.kind == kind
    assert envelope.payload == payload.model_dump()


def test_envelope_forbids_unknown_top_level_fields() -> None:
    data: dict[str, Any] = {
        "v": 1,
        "id": "message-1",
        "kind": "health",
        "payload": {},
        "unexpected": True,
    }

    with pytest.raises(ValidationError):
        Envelope.model_validate(data)
