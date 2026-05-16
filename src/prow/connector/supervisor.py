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

"""Supervisor owning many :class:`ConnectorInstance` records — lifecycle + health probes."""

from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from opentelemetry.metrics import Meter

from prow.connector.entry_point_resolve import (
    secret_field_paths_for_entry_point,
    validate_connector_instance_config,
)
from prow.connector.instance import ConnectorInstance
from prow.connector.log_forwarder import LogForwarder
from prow.connector.metric_forwarder import MetricForwarder
from prow.connector.protocol.messages import EmitAckPayload, HealthStatus
from prow.connector.restart_policy import RestartPolicy
from prow.connector.supervisor_state import ConnectorState

logger = structlog.get_logger(__name__)

EmitHandler = Callable[[str, dict[str, Any]], Awaitable[EmitAckPayload]]
StateGetHandler = Callable[[str, str], Awaitable[Any | None]]
StateSetHandler = Callable[[str, str, Any], Awaitable[None]]


class Supervisor:
    """Owns many :class:`ConnectorInstance` records — parallel start/shutdown + probing."""

    def __init__(
        self,
        runtime_version: str,
        emit_handler: EmitHandler,
        state_get_handler: StateGetHandler,
        state_set_handler: StateSetHandler,
        default_restart_policy: RestartPolicy | None = None,
        health_probe_interval_seconds: float | None = 30.0,
        meter: Meter | None = None,
    ) -> None:
        self._runtime_version = runtime_version
        self._emit_handler = emit_handler
        self._state_get_handler = state_get_handler
        self._state_set_handler = state_set_handler
        self._meter = meter
        self._default_restart_policy = default_restart_policy or RestartPolicy()
        self._health_probe_interval_seconds = health_probe_interval_seconds

        self._instances: dict[str, ConnectorInstance] = {}
        self._health_task: asyncio.Task[None] | None = None
        self._health_consecutive_misses: dict[str, int] = defaultdict(int)

    def add_instance(
        self,
        instance_id: str,
        entry_point_name: str,
        config: dict[str, Any],
        restart_policy: RestartPolicy | None = None,
        *,
        subprocess_extra_environ: dict[str, str] | None = None,
    ) -> ConnectorInstance:
        validate_connector_instance_config(entry_point_name, config)
        policy = restart_policy or self._default_restart_policy
        secret_paths = secret_field_paths_for_entry_point(entry_point_name)
        log_forwarder = LogForwarder(instance_id, entry_point_name, secret_paths)
        metric_forwarder = MetricForwarder(instance_id, entry_point_name, self._meter)
        inst = ConnectorInstance(
            instance_id,
            entry_point_name,
            config,
            self._runtime_version,
            self._emit_handler,
            self._state_get_handler,
            self._state_set_handler,
            policy,
            log_forwarder=log_forwarder,
            metric_forwarder=metric_forwarder,
            subprocess_extra_environ=subprocess_extra_environ,
        )
        self._instances[instance_id] = inst
        return inst

    async def start_all(self) -> None:
        async def _safe_start(inst: ConnectorInstance) -> None:
            try:
                await inst.start()
            except Exception as exc:
                logger.exception(
                    "connector.supervisor.start_instance_failed",
                    connector_instance_id=inst.instance_id,
                    entry_point=inst.entry_point_name,
                    error=str(exc),
                )

        await asyncio.gather(*[_safe_start(i) for i in self._instances.values()])

    async def shutdown_all(self, grace_period_seconds: int = 30) -> None:
        if self._health_task is not None:
            self._health_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._health_task
            self._health_task = None
        await asyncio.gather(
            *[
                i.request_shutdown(grace_period_seconds=grace_period_seconds)
                for i in self._instances.values()
            ],
        )
        await asyncio.gather(*[i.join_background_tasks() for i in self._instances.values()])

    def get_instance(self, instance_id: str) -> ConnectorInstance:
        return self._instances[instance_id]

    def list_instances(self) -> list[ConnectorInstance]:
        return list(self._instances.values())

    async def clear_circuit_break(self, instance_id: str) -> None:
        await self._instances[instance_id].clear_circuit_break()

    async def _health_probe_loop(self) -> None:
        interval = self._health_probe_interval_seconds
        if interval is None:
            return
        try:
            while True:
                await asyncio.sleep(interval)
                for inst in list(self._instances.values()):
                    iid = inst.instance_id
                    if inst.state not in (ConnectorState.READY, ConnectorState.RUNNING):
                        self._health_consecutive_misses[iid] = 0
                        continue
                    try:
                        ack = await inst.probe_health(timeout=5.0)
                    except Exception as exc:
                        logger.exception(
                            "connector.supervisor.health_probe_exception",
                            connector_instance_id=inst.instance_id,
                            error=str(exc),
                        )
                        self._health_consecutive_misses[iid] += 1
                    else:
                        if ack.status in (HealthStatus.HEALTHY, HealthStatus.DEGRADED):
                            self._health_consecutive_misses[iid] = 0
                            continue
                        self._health_consecutive_misses[iid] += 1

                    if self._health_consecutive_misses[iid] < 2:
                        continue
                    self._health_consecutive_misses[iid] = 0
                    try:
                        await inst._mark_unhealthy()
                    except Exception as exc:
                        logger.exception(
                            "connector.supervisor.health_remediate_failed",
                            connector_instance_id=inst.instance_id,
                            error=str(exc),
                        )
        except asyncio.CancelledError:
            return

    async def start_health_probes(self) -> None:
        """Start the periodic health probe loop (idempotent)."""

        if self._health_probe_interval_seconds is None:
            return
        if self._health_task is not None and not self._health_task.done():
            return
        self._health_task = asyncio.create_task(
            self._health_probe_loop(),
            name="connector-supervisor-health",
        )

    async def __aenter__(self) -> Supervisor:
        await self.start_all()
        await self.start_health_probes()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object,
    ) -> None:
        await self.shutdown_all()
