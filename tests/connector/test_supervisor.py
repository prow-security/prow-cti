# Copyright 2026 Prow Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
#
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Integration tests for :class:`prow.connector.supervisor.Supervisor`."""

from __future__ import annotations

from typing import Any

import pytest

from prow.connector import instance as instance_mod
from prow.connector.protocol.messages import EmitAckPayload
from prow.connector.supervisor import Supervisor


@pytest.mark.slow
@pytest.mark.asyncio
async def test_start_all_three_instances_shutdown_all() -> None:
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
    sup.add_instance("a", "minimal_test", {"token": "x"})
    sup.add_instance("b", "minimal_test", {"token": "y"})
    sup.add_instance("c", "minimal_test", {"token": "z"})
    await sup.start_all()
    assert len(sup.list_instances()) == 3
    await sup.shutdown_all(15)


@pytest.mark.asyncio
async def test_start_all_logs_failure_and_keeps_others(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    caplog.set_level(logging.ERROR)

    async def emit(_i: str, _b: dict[str, Any]) -> EmitAckPayload:
        return EmitAckPayload(accepted=0, duplicates=0, validation_failures=[])

    async def get_s(_i: str, _k: str) -> Any | None:
        return None

    async def set_s(_i: str, _k: str, _v: Any) -> None:
        return None

    orig_start = instance_mod.ConnectorInstance.start

    async def patched_start(self: instance_mod.ConnectorInstance) -> None:
        if self.instance_id == "b":
            raise RuntimeError("boom")
        await orig_start(self)

    monkeypatch.setattr(instance_mod.ConnectorInstance, "start", patched_start)

    sup = Supervisor("0.0.0", emit, get_s, set_s, health_probe_interval_seconds=None)
    sup.add_instance("a", "minimal_test", {"token": "x"})
    sup.add_instance("b", "minimal_test", {"token": "y"})
    sup.add_instance("c", "minimal_test", {"token": "z"})
    await sup.start_all()
    ok = [
        i.instance_id
        for i in sup.list_instances()
        if i.state.name not in ("not_started", "starting")
    ]
    assert "a" in ok and "c" in ok and len(ok) >= 2
    await sup.shutdown_all(15)


@pytest.mark.slow
@pytest.mark.asyncio
async def test_async_context_manager_lifecycle() -> None:
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
    sup.add_instance("ctx", "minimal_test", {"token": "x"})
    async with sup as entered:
        assert entered is sup
    assert sup._health_task is None
