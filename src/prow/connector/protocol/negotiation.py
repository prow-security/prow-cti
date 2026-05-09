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

"""Hello/hello-ack negotiation helpers for connector protocol v1."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from prow.connector.protocol.codec import ProtocolError
from prow.connector.protocol.framing import (
    StreamClosedBeforeLineError,
    read_one_envelope,
    write_message,
)
from prow.connector.protocol.messages import (
    Envelope,
    ErrorBody,
    ErrorCode,
    HelloAckPayload,
    HelloPayload,
)

DEFAULT_SUPPORTED_VERSIONS = [1]


class UnsupportedVersionError(ProtocolError):
    """Raised when peers cannot agree on a protocol version."""

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(ErrorCode.UNSUPPORTED_VERSION, message, details=details)


class NegotiationTimeoutError(ProtocolError):
    """Raised when the peer does not complete hello negotiation in time."""

    def __init__(self, message: str) -> None:
        super().__init__(ErrorCode.MALFORMED_MESSAGE, message)


def _message_id() -> str:
    return uuid4().hex


def _highest_overlap(left: list[int], right: list[int]) -> int | None:
    overlap = set(left).intersection(right)
    if not overlap:
        return None
    return max(overlap)


async def _read_one(
    reader: asyncio.StreamReader,
    *,
    timeout_seconds: float,
) -> Envelope:
    try:
        return await asyncio.wait_for(
            read_one_envelope(reader),
            timeout=timeout_seconds,
        )
    except TimeoutError as exc:
        raise NegotiationTimeoutError("Timed out waiting for hello negotiation.") from exc
    except StreamClosedBeforeLineError as exc:
        raise ProtocolError(
            ErrorCode.MALFORMED_MESSAGE,
            "Stream closed before hello negotiation completed.",
        ) from exc


def _validate_hello_payload(envelope: Envelope) -> HelloPayload:
    try:
        return HelloPayload.model_validate(envelope.payload)
    except ValidationError as exc:
        raise ProtocolError(
            ErrorCode.MALFORMED_MESSAGE,
            "Hello payload does not match the protocol schema.",
            details={"errors": exc.errors()},
        ) from exc


def _validate_hello_ack_payload(envelope: Envelope) -> HelloAckPayload:
    try:
        return HelloAckPayload.model_validate(envelope.payload)
    except ValidationError as exc:
        raise ProtocolError(
            ErrorCode.MALFORMED_MESSAGE,
            "Hello-ack payload does not match the protocol schema.",
            details={"errors": exc.errors()},
        ) from exc


async def perform_hello_runtime(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    runtime_version: str,
    config: dict[str, Any],
    supported_versions: list[int] = DEFAULT_SUPPORTED_VERSIONS,
    timeout_seconds: float = 5.0,
) -> int:
    """Runtime side: send hello, await hello-ack, return the agreed version."""

    hello_id = _message_id()
    hello_payload = HelloPayload(
        runtime_version=runtime_version,
        supported_protocol_versions=supported_versions,
        config=config,
    )
    await write_message(
        writer,
        Envelope(
            v=max(supported_versions),
            id=hello_id,
            kind="hello",
            payload=hello_payload.model_dump(),
        ),
    )

    response = await _read_one(reader, timeout_seconds=timeout_seconds)
    if response.error is not None:
        if response.error.code is ErrorCode.UNSUPPORTED_VERSION:
            raise UnsupportedVersionError(response.error.message, details=response.error.details)
        raise ProtocolError(
            response.error.code,
            response.error.message,
            details=response.error.details,
        )
    if response.kind != "hello-ack":
        raise ProtocolError(
            ErrorCode.MALFORMED_MESSAGE,
            "Expected hello-ack during protocol negotiation.",
            details={"kind": response.kind},
        )

    ack_payload = _validate_hello_ack_payload(response)
    agreed_version = _highest_overlap(supported_versions, [ack_payload.protocol_version])
    if agreed_version is None:
        details = {
            "runtime_supported_versions": supported_versions,
            "connector_protocol_version": ack_payload.protocol_version,
        }
        error = ErrorBody(
            code=ErrorCode.UNSUPPORTED_VERSION,
            message="Connector requested an unsupported protocol version.",
            details=details,
        )
        await write_message(
            writer,
            Envelope(
                v=max(supported_versions),
                id=_message_id(),
                kind="hello-ack",
                payload={},
                id_ref=response.id,
                error=error,
            ),
        )
        raise UnsupportedVersionError(error.message, details=details)

    return agreed_version


async def perform_hello_connector(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    connector_version: str,
    supported_versions: list[int] = DEFAULT_SUPPORTED_VERSIONS,
    timeout_seconds: float = 5.0,
) -> tuple[int, dict[str, Any]]:
    """Connector side: await hello, send hello-ack, return version and config."""

    hello = await _read_one(reader, timeout_seconds=timeout_seconds)
    if hello.error is not None:
        raise ProtocolError(hello.error.code, hello.error.message, details=hello.error.details)
    if hello.kind != "hello":
        raise ProtocolError(
            ErrorCode.MALFORMED_MESSAGE,
            "Expected hello during protocol negotiation.",
            details={"kind": hello.kind},
        )

    hello_payload = _validate_hello_payload(hello)
    agreed_version = _highest_overlap(
        hello_payload.supported_protocol_versions,
        supported_versions,
    )
    advertised_version = agreed_version if agreed_version is not None else max(supported_versions)
    ack_payload = HelloAckPayload(
        connector_version=connector_version,
        protocol_version=advertised_version,
    )
    await write_message(
        writer,
        Envelope(
            v=hello.v,
            id=_message_id(),
            kind="hello-ack",
            payload=ack_payload.model_dump(),
            id_ref=hello.id,
        ),
    )

    if agreed_version is None:
        response = await _read_one(reader, timeout_seconds=timeout_seconds)
        if response.error is not None and response.error.code is ErrorCode.UNSUPPORTED_VERSION:
            raise UnsupportedVersionError(response.error.message, details=response.error.details)
        raise UnsupportedVersionError(
            "No overlapping connector protocol version.",
            details={
                "runtime_supported_versions": hello_payload.supported_protocol_versions,
                "connector_supported_versions": supported_versions,
            },
        )

    return agreed_version, hello_payload.config
