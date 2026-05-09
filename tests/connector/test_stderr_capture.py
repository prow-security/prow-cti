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
from typing import Any

import pytest

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
async def test_stderr_ring_buffer_and_logging() -> None:
    async def emit(_i: str, _b: dict[str, Any]) -> EmitAckPayload:
        return EmitAckPayload(accepted=0, duplicates=0, validation_failures=[])

    async def get_s(_i: str, _k: str) -> Any | None:
        return None

    async def set_s(_i: str, _k: str, _v: Any) -> None:
        return None

    sup = Supervisor(
        "0.0.0",
        emit,
        get_s,
        set_s,
        health_probe_interval_seconds=None,
    )
    sup.add_instance("err", "stderr_chatty_test", {"token": "x"})
    await sup.start_all()
    inst = sup.get_instance("err")
    await _wait_ready(inst)
    proc = inst._process
    assert proc is not None
    await sup.shutdown_all(25)

    lines = proc.captured_stderr
    assert len(lines) == 200
    assert lines[0] == "err50"
    assert lines[-1] == "err249"
