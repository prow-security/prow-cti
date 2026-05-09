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

import asyncio
import json
from typing import Any

import pytest
import structlog
from structlog.testing import capture_logs

from prow.connector.protocol.messages import EmitAckPayload
from prow.connector.supervisor import Supervisor
from prow.connector.supervisor_state import ConnectorState


async def _wait_ready(inst: Any, *, timeout_s: float = 15.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        if inst.state == ConnectorState.READY:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"timeout waiting for READY, last state={inst.state!r}")


@pytest.mark.slow
@pytest.mark.asyncio
async def test_secret_fields_redacted_end_to_end() -> None:
    structlog.reset_defaults()

    async def emit(_i: str, _b: dict[str, Any]) -> EmitAckPayload:
        return EmitAckPayload(accepted=0, duplicates=0, validation_failures=[])

    async def get_s(_i: str, _k: str) -> Any | None:
        return None

    async def set_s(_i: str, _k: str, _v: Any) -> None:
        return None

    secret_value = "secret123-never-log-raw"  # noqa: S105

    with capture_logs() as cap:
        sup = Supervisor(
            "0.0.0",
            emit,
            get_s,
            set_s,
            health_probe_interval_seconds=None,
        )
        sup.add_instance(
            "sec",
            "secret_logger_test",
            {"api_key": secret_value},
        )
        await sup.start_all()
        inst = sup.get_instance("sec")
        await _wait_ready(inst)
        await sup.shutdown_all(20)

    blob = json.dumps(cap)
    assert secret_value not in blob
    assert "<redacted>" in blob
    assert "literal-not-nested" in blob
    assert "tok-secret" not in blob
