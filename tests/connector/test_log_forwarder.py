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
# WITHOUT WARRANTIES OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from prow.connector.log_forwarder import LogForwarder
from prow.connector.protocol.messages import LogLevel, LogPayload


def test_forward_info_with_fields() -> None:
    logger = MagicMock()
    logger.bind.return_value = logger
    lf = LogForwarder(
        "inst-1",
        "minimal_test",
        frozenset(),
        logger=logger,
    )
    ts = datetime(2026, 5, 9, 12, 0, 0, tzinfo=UTC)
    lf.forward(
        LogPayload(
            level=LogLevel.INFO,
            message="hello",
            timestamp=ts,
            fields={"k": "v"},
            exception=None,
        ),
    )
    logger.bind.assert_called_once()
    logger.info.assert_called_once()
    args, kwargs = logger.info.call_args
    assert args[0] == "hello"
    assert kwargs["k"] == "v"
    assert kwargs["connector_timestamp"] == ts.isoformat()


def test_forward_exception_as_exc_info_kwarg() -> None:
    logger = MagicMock()
    logger.bind.return_value = logger
    lf = LogForwarder("i", "e", frozenset(), logger=logger)
    ts = datetime.now(UTC)
    lf.forward(
        LogPayload(
            level=LogLevel.ERROR,
            message="boom",
            timestamp=ts,
            fields={},
            exception="Traceback (most recent call last):\n  File ...",
        ),
    )
    kwargs = logger.error.call_args[1]
    assert kwargs["exc_info"].startswith("Traceback")


def test_redact_secret_top_level_and_nested() -> None:
    logger = MagicMock()
    logger.bind.return_value = logger
    lf = LogForwarder(
        "i",
        "e",
        frozenset({"api_key", "nested.token"}),
        logger=logger,
    )
    ts = datetime.now(UTC)
    lf.forward(
        LogPayload(
            level=LogLevel.INFO,
            message="m",
            timestamp=ts,
            fields={
                "api_key": "secret123",
                "nested": {"token": "tok"},
                "auth.token": "literal",
            },
            exception=None,
        ),
    )
    kwargs = logger.info.call_args[1]
    assert kwargs["api_key"] == "<redacted>"
    assert kwargs["nested"]["token"] == "<redacted>"  # noqa: S105
    assert kwargs["auth.token"] == "literal"


def test_forward_logger_raises_fail_soft() -> None:
    bad = MagicMock()
    bad.bind.return_value = bad
    bad.info.side_effect = RuntimeError("no log for you")

    lf = LogForwarder("i", "e", frozenset(), logger=bad)
    lf.forward(
        LogPayload(
            level=LogLevel.INFO,
            message="x",
            timestamp=datetime.now(UTC),
            fields={},
            exception=None,
        ),
    )


def test_level_mapping_uses_correct_method() -> None:
    logger = MagicMock()
    logger.bind.return_value = logger
    lf = LogForwarder("i", "e", frozenset(), logger=logger)
    ts = datetime.now(UTC)
    payload = LogPayload(
        level=LogLevel.WARNING,
        message="w",
        timestamp=ts,
        fields={},
        exception=None,
    )
    lf.forward(payload)
    logger.warning.assert_called_once()
