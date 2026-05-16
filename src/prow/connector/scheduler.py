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

"""Interval scheduler that triggers connector fetch cycles."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from datetime import timedelta

import structlog

from prow.connector.duration import parse_iso8601_duration
from prow.connector.supervisor import Supervisor
from prow.connector.supervisor_state import ConnectorState

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class _ScheduledInstance:
    instance_id: str
    interval: timedelta


class ConnectorScheduler:
    """Triggers connector fetch() cycles on an interval after each run completes."""

    def __init__(self, supervisor: Supervisor) -> None:
        self._supervisor = supervisor
        self._schedules: list[_ScheduledInstance] = []
        self._tasks: list[asyncio.Task[None]] = []
        self._stop_event = asyncio.Event()

    def register(self, instance_id: str, schedule: str) -> None:
        """Record an instance and its interval. Call before :meth:`start`."""

        interval = parse_iso8601_duration(schedule)
        self._schedules.append(_ScheduledInstance(instance_id=instance_id, interval=interval))

    async def start(self) -> None:
        """Spawn one asyncio loop task per registered instance."""

        self._stop_event.clear()
        self._tasks = [
            asyncio.create_task(
                self._run_loop(entry.instance_id, entry.interval),
                name=f"connector-scheduler-{entry.instance_id}",
            )
            for entry in self._schedules
        ]

    async def stop(self) -> None:
        """Cancel scheduler tasks and wait for them to finish."""

        self._stop_event.set()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()

    async def _run_loop(self, instance_id: str, interval: timedelta) -> None:
        try:
            while not self._stop_event.is_set():
                inst = self._supervisor.get_instance(instance_id)
                if inst.state == ConnectorState.CIRCUIT_BROKEN:
                    logger.info(
                        "connector.scheduler.skip_circuit_broken",
                        connector_instance_id=instance_id,
                    )
                else:
                    try:
                        await inst.run_fetch()
                        await inst.wait_until_idle()
                    except Exception as exc:
                        logger.exception(
                            "connector.scheduler.fetch_failed",
                            connector_instance_id=instance_id,
                            error=str(exc),
                        )

                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=interval.total_seconds(),
                    )
                    break
                except TimeoutError:
                    continue
        except asyncio.CancelledError:
            return
