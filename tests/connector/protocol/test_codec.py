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

"""Tests for connector protocol codec helpers."""

from __future__ import annotations

import pytest

from prow.connector.protocol.codec import (
    MessageTooLargeError,
    ProtocolError,
    decode,
    encode,
)
from prow.connector.protocol.messages import Envelope, ErrorCode


def test_encode_appends_newline() -> None:
    envelope = Envelope(v=1, id="message-1", kind="health")

    encoded = encode(envelope)

    assert encoded.endswith(b"\n")


def test_decode_round_trips_encoded_envelope_losslessly() -> None:
    envelope = Envelope(v=1, id="message-1", kind="health", payload={})

    decoded = decode(encode(envelope))

    assert decoded == envelope


def test_decode_invalid_utf8_raises_protocol_error() -> None:
    with pytest.raises(ProtocolError) as error:
        decode(b"\xff\n")

    assert error.value.code is ErrorCode.MALFORMED_MESSAGE


def test_decode_invalid_json_raises_protocol_error() -> None:
    with pytest.raises(ProtocolError) as error:
        decode(b"{not json}\n")

    assert error.value.code is ErrorCode.MALFORMED_MESSAGE


def test_decode_missing_required_field_raises_protocol_error() -> None:
    with pytest.raises(ProtocolError) as error:
        decode(b'{"v":1,"kind":"health","payload":{}}\n')

    assert error.value.code is ErrorCode.MALFORMED_MESSAGE


def test_encode_message_over_one_mib_raises_message_too_large() -> None:
    envelope = Envelope(v=1, id="message-1", kind="log", payload={"blob": "x" * (1 << 20)})

    with pytest.raises(MessageTooLargeError):
        encode(envelope)
