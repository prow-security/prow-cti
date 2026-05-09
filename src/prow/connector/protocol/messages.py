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

"""Typed connector protocol envelopes and payloads."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ErrorCode(StrEnum):
    """Well-known connector protocol error codes."""

    UNSUPPORTED_VERSION = "unsupported-version"
    """The peer requested a protocol version this side cannot speak."""

    MALFORMED_MESSAGE = "malformed-message"
    """A message could not be decoded, parsed, or envelope-validated."""

    UNKNOWN_KIND = "unknown-kind"
    """The envelope kind is not known to this protocol version."""

    VALIDATION_ERROR = "validation-error"
    """A STIX bundle or object failed prow STIX validation."""

    STATE_KEY_TOO_LARGE = "state-key-too-large"
    """A connector state key exceeded the configured size budget."""

    STATE_VALUE_TOO_LARGE = "state-value-too-large"
    """A connector state value exceeded the configured size budget."""

    INTERNAL_ERROR = "internal-error"
    """An unexpected runtime or connector failure occurred."""


class LogLevel(StrEnum):
    """Structured connector log levels."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class HealthStatus(StrEnum):
    """Connector health probe statuses."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class ErrorBody(BaseModel):
    """Structured failure body attached to response envelopes."""

    code: ErrorCode
    message: str
    details: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class Envelope(BaseModel):
    """Common envelope for every connector protocol message."""

    v: int
    id: str
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)
    id_ref: str | None = None
    error: ErrorBody | None = None

    model_config = ConfigDict(extra="forbid")


class HelloPayload(BaseModel):
    """Runtime hello payload."""

    runtime_version: str
    supported_protocol_versions: list[int]
    config: dict[str, Any]

    model_config = ConfigDict(extra="forbid")


class HelloAckPayload(BaseModel):
    """Connector hello acknowledgement payload."""

    connector_version: str
    protocol_version: int

    model_config = ConfigDict(extra="forbid")


class ShutdownPayload(BaseModel):
    """Graceful shutdown request payload."""

    grace_period_seconds: int = 30

    model_config = ConfigDict(extra="forbid")


class ShutdownAckPayload(BaseModel):
    """Graceful shutdown acknowledgement payload."""

    model_config = ConfigDict(extra="forbid")


class EmitPayload(BaseModel):
    """Connector STIX bundle emission payload."""

    bundle: dict[str, Any]

    model_config = ConfigDict(extra="forbid")


class ValidationFailure(BaseModel):
    """One STIX object validation failure."""

    object_id: str
    error: str

    model_config = ConfigDict(extra="forbid")


class EmitAckPayload(BaseModel):
    """Runtime acknowledgement for an emitted STIX bundle."""

    accepted: int
    duplicates: int
    validation_failures: list[ValidationFailure]

    model_config = ConfigDict(extra="forbid")


class LogPayload(BaseModel):
    """Structured connector log record payload."""

    level: LogLevel
    message: str
    timestamp: datetime
    fields: dict[str, Any]
    exception: str | None

    model_config = ConfigDict(extra="forbid")


class MetricPayload(BaseModel):
    """Single connector metric observation payload."""

    name: str
    value: float
    unit: str | None
    tags: dict[str, str]
    timestamp: datetime

    model_config = ConfigDict(extra="forbid")


class SetStatePayload(BaseModel):
    """Connector persistent state write payload."""

    key: str
    value: Any

    model_config = ConfigDict(extra="forbid")


class SetStateAckPayload(BaseModel):
    """Connector persistent state write acknowledgement payload."""

    model_config = ConfigDict(extra="forbid")


class GetStatePayload(BaseModel):
    """Connector persistent state read payload."""

    key: str

    model_config = ConfigDict(extra="forbid")


class GetStateAckPayload(BaseModel):
    """Connector persistent state read acknowledgement payload."""

    value: Any | None

    model_config = ConfigDict(extra="forbid")


class HealthPayload(BaseModel):
    """Connector health probe payload."""

    model_config = ConfigDict(extra="forbid")


class HealthAckPayload(BaseModel):
    """Connector health probe acknowledgement payload."""

    status: HealthStatus
    details: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class CancelPayload(BaseModel):
    """Cooperative cancellation request payload."""

    target_id: str

    model_config = ConfigDict(extra="forbid")


class CancelAckPayload(BaseModel):
    """Cooperative cancellation acknowledgement payload."""

    cancelled: bool

    model_config = ConfigDict(extra="forbid")
