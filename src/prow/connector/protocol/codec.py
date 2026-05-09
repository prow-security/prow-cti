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

"""Connector protocol envelope encoding and decoding."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from prow.connector.protocol.messages import Envelope, ErrorCode

MAX_MESSAGE_BYTES = 1 << 20


class ProtocolError(Exception):
    """Base exception for connector protocol failures."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class MessageTooLargeError(ProtocolError):
    """Raised when a protocol line exceeds the maximum byte budget."""

    def __init__(self, message: str, *, size_bytes: int, limit_bytes: int) -> None:
        super().__init__(
            ErrorCode.MALFORMED_MESSAGE,
            message,
            details={"size_bytes": size_bytes, "limit_bytes": limit_bytes},
        )
        self.size_bytes = size_bytes
        self.limit_bytes = limit_bytes


def encode(envelope: Envelope) -> bytes:
    """Serialize one envelope as UTF-8 JSON plus a trailing newline."""

    encoded = envelope.model_dump_json().encode("utf-8") + b"\n"
    if len(encoded) > MAX_MESSAGE_BYTES:
        raise MessageTooLargeError(
            "Encoded protocol message exceeds the maximum line size.",
            size_bytes=len(encoded),
            limit_bytes=MAX_MESSAGE_BYTES,
        )
    return encoded


def decode(line: bytes) -> Envelope:
    """Decode and validate one protocol envelope line."""

    try:
        decoded = line.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProtocolError(
            ErrorCode.MALFORMED_MESSAGE,
            "Protocol message is not valid UTF-8.",
            details={"start": exc.start, "end": exc.end, "reason": exc.reason},
        ) from exc

    if decoded.endswith("\n"):
        decoded = decoded[:-1]

    try:
        data = json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise ProtocolError(
            ErrorCode.MALFORMED_MESSAGE,
            "Protocol message is not valid JSON.",
            details={"line": exc.lineno, "column": exc.colno, "position": exc.pos},
        ) from exc

    try:
        return Envelope.model_validate(data)
    except ValidationError as exc:
        raise ProtocolError(
            ErrorCode.MALFORMED_MESSAGE,
            "Protocol message does not match the envelope schema.",
            details={"errors": exc.errors()},
        ) from exc
