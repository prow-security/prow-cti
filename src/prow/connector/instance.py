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

"""Supervisor-owned connector instance (process + state machine + restart bookkeeping)."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

import structlog

from prow.connector.process import ConnectorProcess, ProcessExitReason
from prow.connector.protocol.messages import EmitAckPayload, HealthAckPayload, HealthStatus
from prow.connector.restart_policy import (
    RestartDecision,
    RestartPolicy,
    trim_restart_timestamps,
    utc_now,
)
from prow.connector.supervisor_state import (
    ConnectorState,
    InvalidStateTransitionError,
    SupervisorTransitionEvent,
    apply_transition,
)

logger = structlog.get_logger(__name__)

EmitHandler = Callable[[str, dict[str, Any]], Awaitable[EmitAckPayload]]
StateGetHandler = Callable[[str, str], Awaitable[Any | None]]
StateSetHandler = Callable[[str, str, Any], Awaitable[None]]

SleepFn = Callable[[float], Awaitable[None]]
ClockFn = Callable[[], datetime]


class ConnectorInstance:
    """Supervisor's per-instance handle — one :class:`ConnectorProcess` at a time."""

    def __init__(
        self,
        instance_id: str,
        entry_point_name: str,
        config: dict[str, Any],
        runtime_version: str,
        emit_handler: EmitHandler,
        state_get_handler: StateGetHandler,
        state_set_handler: StateSetHandler,
        restart_policy: RestartPolicy,
        *,
        subprocess_extra_environ: dict[str, str] | None = None,
        clock: ClockFn | None = None,
        sleep_fn: SleepFn | None = None,
    ) -> None:
        self.instance_id = instance_id
        self.entry_point_name = entry_point_name
        self.config = config
        self._runtime_version = runtime_version
        self._user_emit_handler = emit_handler
        self._state_get_handler = state_get_handler
        self._state_set_handler = state_set_handler
        self._restart_policy = restart_policy
        self._subprocess_extra_environ = dict(subprocess_extra_environ or ())
        self._clock = clock or utc_now
        self._sleep_fn: SleepFn = sleep_fn if sleep_fn is not None else asyncio.sleep

        self._state = ConnectorState.NOT_STARTED
        self._process: ConnectorProcess | None = None
        self._restart_timestamps: list[datetime] = []
        self._last_restart_at: datetime | None = None

        self._lock = asyncio.Lock()
        self._watcher_task: asyncio.Task[None] | None = None
        self._pending_restart_task: asyncio.Task[None] | None = None
        self._shutdown_requested = False

    @property
    def state(self) -> ConnectorState:
        return self._state

    @property
    def restart_attempts_in_window(self) -> int:
        now = self._clock()
        trim_restart_timestamps(
            self._restart_timestamps,
            now=now,
            window_seconds=self._restart_policy.window_duration_seconds,
        )
        return len(self._restart_timestamps)

    @property
    def last_restart_at(self) -> datetime | None:
        return self._last_restart_at

    def _transition_locked(self, event: SupervisorTransitionEvent) -> None:
        self._state = apply_transition(self._state, event)

    def _wrap_emit_handler(self) -> EmitHandler:
        inst = self

        async def _emit(inst_id: str, bundle: dict[str, Any]) -> EmitAckPayload:
            async with inst._lock:
                if inst._state == ConnectorState.READY:
                    with contextlib.suppress(InvalidStateTransitionError):
                        inst._transition_locked(SupervisorTransitionEvent.FIRST_OPERATIONAL_MESSAGE)
            return await inst._user_emit_handler(inst_id, bundle)

        return _emit

    def _new_process(self) -> ConnectorProcess:
        return ConnectorProcess(
            self.instance_id,
            self.entry_point_name,
            self.config,
            self._runtime_version,
            self._wrap_emit_handler(),
            self._state_get_handler,
            self._state_set_handler,
            extra_environ=self._subprocess_extra_environ,
        )

    async def _spawn_process_body(self) -> None:
        """Spawn subprocess after state is already ``starting``."""

        proc = self._new_process()
        self._process = proc

        await proc.start()

        async with self._lock:
            if proc.runtime_transport is None:
                self._transition_locked(SupervisorTransitionEvent.START_FAILURE_TO_CRASHED)
            else:
                self._transition_locked(SupervisorTransitionEvent.HELLO_SUCCEEDED)

        self._cancel_pending_restart_task()
        self._watcher_task = asyncio.create_task(
            self._watcher_loop(proc),
            name=f"connector-watcher-{self.instance_id}",
        )

    async def start(self) -> None:
        """Initial start from ``not_started`` or ``dead``."""

        async with self._lock:
            if self._state not in (ConnectorState.NOT_STARTED, ConnectorState.DEAD):
                raise InvalidStateTransitionError(f"start() invalid from state {self._state!s}")
            self._transition_locked(SupervisorTransitionEvent.START_INVOKED)
            self._shutdown_requested = False

        await self._spawn_process_body()

    async def _watcher_loop(self, proc: ConnectorProcess) -> None:
        try:
            reason = await proc.wait()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(
                "connector.instance.watcher_wait_failed",
                connector_instance_id=self.instance_id,
                state=self._state,
                error=str(exc),
            )
            return

        try:
            await self._handle_process_exit(reason)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(
                "connector.instance.watcher_dispatch_failed",
                connector_instance_id=self.instance_id,
                state=self._state,
                error=str(exc),
            )

    async def _handle_process_exit(self, reason: ProcessExitReason) -> None:
        decision: RestartDecision | None = None
        delay_seconds = 0.0

        async with self._lock:
            if self._state == ConnectorState.DRAINING:
                if reason == ProcessExitReason.GRACEFUL_SHUTDOWN:
                    self._transition_locked(SupervisorTransitionEvent.GRACEFUL_PROCESS_EXIT)
                    self._process = None
                    return
                self._transition_locked(SupervisorTransitionEvent.CRASH_WHILE_DRAINING)
            elif self._state in (ConnectorState.READY, ConnectorState.RUNNING):
                if reason == ProcessExitReason.GRACEFUL_SHUTDOWN:
                    self._transition_locked(SupervisorTransitionEvent.GRACEFUL_EXIT_WITHOUT_DRAIN)
                    self._process = None
                    return
                self._transition_locked(SupervisorTransitionEvent.CRASH_WHILE_ACTIVE)
            elif self._state == ConnectorState.CRASHED:
                pass
            elif self._state == ConnectorState.STARTING:
                self._transition_locked(SupervisorTransitionEvent.START_FAILURE_TO_CRASHED)

            now = self._clock()
            trim_restart_timestamps(
                self._restart_timestamps,
                now=now,
                window_seconds=self._restart_policy.window_duration_seconds,
            )
            self._restart_timestamps.append(now)
            self._last_restart_at = now
            trim_restart_timestamps(
                self._restart_timestamps,
                now=now,
                window_seconds=self._restart_policy.window_duration_seconds,
            )

            decision = self._restart_policy.should_restart(
                reason,
                self._restart_timestamps,
                now=now,
            )

            if decision.action == "stop":
                with contextlib.suppress(InvalidStateTransitionError):
                    self._transition_locked(SupervisorTransitionEvent.POLICY_STOP_TO_DEAD)
                if self._state != ConnectorState.DEAD:
                    self._state = ConnectorState.DEAD
                self._restart_timestamps.clear()
                self._process = None
                return

            if decision.action == "circuit_break":
                with contextlib.suppress(InvalidStateTransitionError):
                    self._transition_locked(SupervisorTransitionEvent.CIRCUIT_BREAK_RECORDED)
                if self._state != ConnectorState.CIRCUIT_BROKEN:
                    self._state = ConnectorState.CIRCUIT_BROKEN
                self._process = None
                return

            delay_seconds = decision.delay_seconds

        self._process = None

        async def _sleep_then_restart() -> None:
            try:
                await self._sleep_fn(delay_seconds)
            except asyncio.CancelledError:
                return
            async with self._lock:
                if self._shutdown_requested:
                    return
                if self._state in (
                    ConnectorState.DEAD,
                    ConnectorState.DRAINING,
                    ConnectorState.CIRCUIT_BROKEN,
                ):
                    return
                try:
                    self._transition_locked(SupervisorTransitionEvent.RESTART_BACKOFF_ELAPSED)
                except InvalidStateTransitionError:
                    return
            try:
                await self._spawn_process_body()
            except Exception as exc:
                logger.exception(
                    "connector.instance.restart_failed",
                    connector_instance_id=self.instance_id,
                    error=str(exc),
                )

        self._pending_restart_task = asyncio.create_task(
            _sleep_then_restart(),
            name=f"connector-restart-{self.instance_id}",
        )

    def _cancel_pending_restart_task(self) -> None:
        if self._pending_restart_task is None:
            return
        self._pending_restart_task.cancel()
        self._pending_restart_task = None

    async def request_shutdown(self, grace_period_seconds: int = 30) -> None:
        async with self._lock:
            self._shutdown_requested = True
            self._cancel_pending_restart_task()
            if self._state == ConnectorState.CRASHED:
                with contextlib.suppress(InvalidStateTransitionError):
                    self._transition_locked(SupervisorTransitionEvent.RESTART_ABORT_TO_DEAD)
                self._state = ConnectorState.DEAD
                self._restart_timestamps.clear()
                self._process = None
                return
            if self._state == ConnectorState.CIRCUIT_BROKEN:
                with contextlib.suppress(InvalidStateTransitionError):
                    self._transition_locked(SupervisorTransitionEvent.SHUTDOWN_REQUESTED)
                self._state = ConnectorState.DEAD
                self._process = None
                return
            proc = self._process
            try:
                if self._state == ConnectorState.STARTING:
                    self._transition_locked(SupervisorTransitionEvent.SHUTDOWN_REQUESTED)
                elif self._state in (ConnectorState.READY, ConnectorState.RUNNING):
                    self._transition_locked(SupervisorTransitionEvent.SHUTDOWN_REQUESTED)
            except InvalidStateTransitionError:
                pass

        if proc is not None:
            try:
                if proc.runtime_transport is None:
                    await proc.terminate_abruptly()
                else:
                    await proc.request_shutdown(grace_period_seconds=grace_period_seconds)
            except Exception as exc:
                logger.warning(
                    "connector.instance.shutdown_grace_failed",
                    connector_instance_id=self.instance_id,
                    error=str(exc),
                    exc_info=True,
                )
                await proc.terminate_abruptly()

    async def clear_circuit_break(self) -> None:
        async with self._lock:
            if self._state != ConnectorState.CIRCUIT_BROKEN:
                raise InvalidStateTransitionError(
                    f"clear_circuit_break invalid from {self._state!s}",
                )
            self._restart_timestamps.clear()
            self._shutdown_requested = False
            self._transition_locked(SupervisorTransitionEvent.CIRCUIT_CLEAR_RESTART)

        await self._spawn_process_body()

    async def probe_health(self, timeout: float = 5.0) -> HealthAckPayload:
        async with self._lock:
            st = self._state
            proc = self._process
        if st not in (ConnectorState.READY, ConnectorState.RUNNING):
            return HealthAckPayload(status=HealthStatus.UNHEALTHY, details={"reason": "not_ready"})
        if proc is None or proc.runtime_transport is None:
            return HealthAckPayload(
                status=HealthStatus.UNHEALTHY, details={"reason": "no_transport"}
            )
        try:
            return await proc.runtime_transport.request_health(timeout=timeout)
        except Exception:
            return HealthAckPayload(
                status=HealthStatus.UNHEALTHY, details={"reason": "probe_failed"}
            )

    async def join_background_tasks(self) -> None:
        pr = self._pending_restart_task
        wt = self._watcher_task
        if pr is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await pr
        if wt is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await wt

    async def cancel_background_tasks(self) -> None:
        self._cancel_pending_restart_task()
        if self._watcher_task is not None:
            self._watcher_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._watcher_task
            self._watcher_task = None

    async def _mark_unhealthy(self) -> None:
        logger.warning(
            "connector.instance.health_remediate_kill",
            connector_instance_id=self.instance_id,
            state=self._state,
        )
        async with self._lock:
            proc = self._process
            st = self._state
        if st not in (ConnectorState.READY, ConnectorState.RUNNING) or proc is None:
            return
        try:
            await proc.terminate_abruptly()
        except Exception as exc:
            logger.exception(
                "connector.instance.health_kill_failed",
                connector_instance_id=self.instance_id,
                error=str(exc),
            )
