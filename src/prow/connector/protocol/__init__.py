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

"""Internal connector wire protocol helpers."""

from prow.connector.protocol.codec import (
    MessageTooLargeError,
    ProtocolError,
    decode,
    encode,
)
from prow.connector.protocol.framing import read_messages, write_message
from prow.connector.protocol.messages import (
    CancelAckPayload,
    CancelPayload,
    EmitAckPayload,
    EmitPayload,
    Envelope,
    ErrorBody,
    ErrorCode,
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
from prow.connector.protocol.negotiation import (
    NegotiationTimeoutError,
    UnsupportedVersionError,
    perform_hello_connector,
    perform_hello_runtime,
)

__all__ = [
    "CancelAckPayload",
    "CancelPayload",
    "EmitAckPayload",
    "EmitPayload",
    "Envelope",
    "ErrorBody",
    "ErrorCode",
    "GetStateAckPayload",
    "GetStatePayload",
    "HealthAckPayload",
    "HealthPayload",
    "HealthStatus",
    "HelloAckPayload",
    "HelloPayload",
    "LogLevel",
    "LogPayload",
    "MessageTooLargeError",
    "MetricPayload",
    "NegotiationTimeoutError",
    "ProtocolError",
    "SetStateAckPayload",
    "SetStatePayload",
    "ShutdownAckPayload",
    "ShutdownPayload",
    "UnsupportedVersionError",
    "ValidationFailure",
    "decode",
    "encode",
    "perform_hello_connector",
    "perform_hello_runtime",
    "read_messages",
    "write_message",
]
