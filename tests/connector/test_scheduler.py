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

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from prow.connector.protocol.messages import EmitAckPayload
from prow.connector.scheduler import ConnectorScheduler
from prow.connector.supervisor import Supervisor
from prow.connector.supervisor_state import ConnectorState


class _FakeInstance:
    def __init__(self, instance_id: str) -> None:
        self.instance_id = instance_id
        self.state = ConnectorState.DEAD
        self.run_fetch_calls = 0
        self._fetch_seconds = 0.0

    async def run_fetch(self) -> None:
        self.run_fetch_calls += 1
        if self._fetch_seconds:
            await asyncio.sleep(self._fetch_seconds)

    async def wait_until_idle(self) -> None:
        return


async def _noop_state_get(_i: str, _k: str) -> Any | None:
    return None


async def _noop_state_set(_i: str, _k: str, _v: Any) -> None:
    return None


async def _noop_emit(_i: str, _b: dict[str, Any]) -> EmitAckPayload:
    return EmitAckPayload(accepted=0, duplicates=0, validation_failures=[])


def _test_supervisor() -> Supervisor:
    return Supervisor(
        "0.0.0",
        _noop_emit,
        _noop_state_get,
        _noop_state_set,
        health_probe_interval_seconds=None,
    )


@pytest.mark.asyncio
async def test_scheduler_runs_fetch_after_interval() -> None:
    fake = _FakeInstance("inst-a")
    sup = _test_supervisor()
    sup._instances["inst-a"] = fake  # type: ignore[assignment]

    sched = ConnectorScheduler(sup)
    sched.register("inst-a", "1s")
    await sched.start()
    await asyncio.sleep(2.5)
    await sched.stop()

    assert fake.run_fetch_calls >= 2


@pytest.mark.asyncio
async def test_scheduler_interval_after_completion() -> None:
    fake = _FakeInstance("inst-b")
    fake._fetch_seconds = 0.2
    sup = _test_supervisor()
    sup._instances["inst-b"] = fake  # type: ignore[assignment]

    sched = ConnectorScheduler(sup)
    sched.register("inst-b", "1s")
    await sched.start()

    while fake.run_fetch_calls < 1:
        await asyncio.sleep(0.05)
    first_done = asyncio.get_event_loop().time()
    while fake.run_fetch_calls < 2:
        await asyncio.sleep(0.05)
    second_start_gap = asyncio.get_event_loop().time() - first_done

    await sched.stop()
    assert second_start_gap >= 1.0


@pytest.mark.asyncio
async def test_scheduler_skips_circuit_broken() -> None:
    fake = _FakeInstance("inst-c")
    fake.state = ConnectorState.CIRCUIT_BROKEN
    sup = _test_supervisor()
    sup._instances["inst-c"] = fake  # type: ignore[assignment]

    sched = ConnectorScheduler(sup)
    sched.register("inst-c", "1s")
    await sched.start()
    await asyncio.sleep(0.3)
    await sched.stop()

    assert fake.run_fetch_calls == 0


@pytest.mark.asyncio
async def test_scheduler_stop_cancels_tasks() -> None:
    fake = _FakeInstance("inst-d")
    sup = _test_supervisor()
    sup._instances["inst-d"] = fake  # type: ignore[assignment]

    sched = ConnectorScheduler(sup)
    sched.register("inst-d", "1h")
    await sched.start()
    await sched.stop()
    assert all(t.done() for t in sched._tasks)


def test_register_invalid_duration_raises() -> None:
    sched = ConnectorScheduler(_test_supervisor())
    with pytest.raises(ValueError, match="invalid schedule duration"):
        sched.register("x", "weekly")
