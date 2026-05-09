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

"""Spawn and supervise a single connector subprocess (Pass C1 subset)."""

from __future__ import annotations

import asyncio
import contextlib
import sys
from collections import deque
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Any

import structlog

from prow.connector.pipe_stdio import connector_subprocess_environ
from prow.connector.protocol.codec import ProtocolError
from prow.connector.protocol.messages import EmitAckPayload, LogLevel, LogPayload, MetricPayload
from prow.connector.protocol.negotiation import (
    UnsupportedVersionError,
    perform_hello_runtime,
)
from prow.connector.runtime_transport import ConnectorRuntimeTransport

logger = structlog.get_logger(__name__)

EmitHandler = Callable[[str, dict[str, Any]], Awaitable[EmitAckPayload]]
StateGetHandler = Callable[[str, str], Awaitable[Any | None]]
StateSetHandler = Callable[[str, str, Any], Awaitable[None]]
LogHandler = Callable[[LogPayload], None]
MetricHandler = Callable[[MetricPayload], None]


class _StderrRingBuffer:
    """Recent stderr lines bounded by line count and approximate UTF-8 byte size."""

    def __init__(self, max_lines: int, max_bytes: int) -> None:
        self._lines: deque[str] = deque()
        self._max_lines = max_lines
        self._max_bytes = max_bytes
        self._approx_bytes = 0

    def append(self, line: str) -> None:
        raw = line.encode("utf-8")
        self._lines.append(line)
        self._approx_bytes += len(raw) + 1
        self._trim()

    def _trim(self) -> None:
        while self._lines and (
            len(self._lines) > self._max_lines or self._approx_bytes > self._max_bytes
        ):
            old = self._lines.popleft()
            self._approx_bytes -= len(old.encode("utf-8")) + 1

    def snapshot(self) -> list[str]:
        return list(self._lines)


class ConnectorProcessState(StrEnum):
    """Minimal lifecycle surface for Pass C1 introspection."""

    NOT_STARTED = "not_started"
    RUNNING = "running"
    DRAINING = "draining"
    EXITED = "exited"


class ProcessExitReason(StrEnum):
    """Why :meth:`ConnectorProcess.wait` returned."""

    GRACEFUL_SHUTDOWN = "graceful_shutdown"
    CRASHED = "crashed"
    TIMEOUT_KILLED = "timeout_killed"
    PROTOCOL_ERROR = "protocol_error"
    HELLO_FAILED = "hello_failed"
    SUBPROCESS_SPAWN_FAILED = "subprocess_spawn_failed"


class ConnectorProcess:
    """Owns one subprocess, pipes, and :class:`ConnectorRuntimeTransport`."""

    def __init__(
        self,
        connector_instance_id: str,
        entry_point_name: str,
        config: dict[str, Any],
        runtime_version: str,
        emit_handler: EmitHandler,
        state_get_handler: StateGetHandler,
        state_set_handler: StateSetHandler,
        *,
        log_handler: LogHandler | None = None,
        metric_handler: MetricHandler | None = None,
        stderr_log_level: LogLevel = LogLevel.ERROR,
        stderr_max_lines: int = 200,
        stderr_max_bytes: int = 10 * 1024,
        extra_environ: dict[str, str] | None = None,
    ) -> None:
        self._connector_instance_id = connector_instance_id
        self._entry_point_name = entry_point_name
        self._config = config
        self._runtime_version = runtime_version
        self._emit_handler = emit_handler
        self._state_get_handler = state_get_handler
        self._state_set_handler = state_set_handler
        self._log_handler = log_handler
        self._metric_handler = metric_handler
        self._stderr_log_level = stderr_log_level
        self._stderr_ring = _StderrRingBuffer(stderr_max_lines, stderr_max_bytes)
        self._extra_environ = dict(extra_environ or ())

        self._proc: asyncio.subprocess.Process | None = None
        self._transport: ConnectorRuntimeTransport | None = None
        self._stderr_task: asyncio.Task[None] | None = None

        self._state = ConnectorProcessState.NOT_STARTED
        self._timeout_kill = False
        self._spawn_failed = False
        self._hello_failed = False

    @property
    def captured_stderr(self) -> list[str]:
        """Returns the most recent stderr lines (up to ring buffer capacity)."""

        return self._stderr_ring.snapshot()

    @property
    def state(self) -> ConnectorProcessState:
        return self._state

    @property
    def runtime_transport(self) -> ConnectorRuntimeTransport | None:
        return self._transport

    async def start(self) -> None:
        """Spawn subprocess, negotiate hello, start runtime transport dispatch."""

        if self._state != ConnectorProcessState.NOT_STARTED:
            raise RuntimeError("ConnectorProcess.start may only be called once.")

        base_env = {
            "PROW_CONNECTOR_INSTANCE_ID": self._connector_instance_id,
            "PROW_CONNECTOR_ENTRY_POINT": self._entry_point_name,
        }
        base_env.update(self._extra_environ)
        env = connector_subprocess_environ(base_env)

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                "from prow.connector.runner import main; main()",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except OSError as exc:
            self._spawn_failed = True
            self._state = ConnectorProcessState.EXITED
            logger.error(
                "connector.process.spawn_failed",
                connector_instance_id=self._connector_instance_id,
                error=str(exc),
                exc_info=True,
            )
            return

        self._proc = proc
        if proc.stdin is None or proc.stdout is None or proc.stderr is None:
            raise RuntimeError("asyncio subprocess is missing stdio pipes.")

        self._stderr_task = asyncio.create_task(
            self._drain_stderr(proc.stderr),
            name=f"connector-stderr-{self._connector_instance_id}",
        )

        reader = proc.stdout
        writer = proc.stdin

        try:
            protocol_version = await perform_hello_runtime(
                reader,
                writer,
                self._runtime_version,
                self._config,
                timeout_seconds=30.0,
            )
        except (ProtocolError, UnsupportedVersionError, TimeoutError) as exc:
            self._hello_failed = True
            logger.error(
                "connector.process.hello_failed",
                connector_instance_id=self._connector_instance_id,
                error=str(exc),
                exc_info=True,
            )
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(proc.wait(), timeout=30.0)
            await self._join_stderr_task()
            self._state = ConnectorProcessState.EXITED
            return

        self._transport = ConnectorRuntimeTransport(
            self._connector_instance_id,
            reader,
            writer,
            protocol_version,
            self._emit_handler,
            self._state_get_handler,
            self._state_set_handler,
            log_handler=self._log_handler,
            metric_handler=self._metric_handler,
        )
        await self._transport.start()
        self._state = ConnectorProcessState.RUNNING

    async def _drain_stderr(self, stream: asyncio.StreamReader) -> None:
        bind = structlog.contextvars.bind_contextvars(
            connector_instance_id=self._connector_instance_id,
        )
        log_fn = getattr(logger, self._stderr_log_level.value, logger.error)
        try:
            while True:
                line = await stream.readline()
                if not line:
                    return
                text = line.decode("utf-8", errors="replace").rstrip()
                self._stderr_ring.append(text)
                log_fn("connector.subprocess.stderr", message=text)
        finally:
            structlog.contextvars.reset_contextvars(**bind)

    async def _join_stderr_task(self) -> None:
        if self._stderr_task is None:
            return
        with contextlib.suppress(Exception):
            await self._stderr_task
        self._stderr_task = None

    async def terminate_abruptly(self) -> None:
        """Kill the subprocess without graceful shutdown (supervisor remediation)."""

        proc = self._proc
        if proc is None:
            return
        try:
            proc.kill()
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(proc.wait(), timeout=30.0)
        except TimeoutError:
            logger.error(
                "connector.process.kill_wait_timeout",
                connector_instance_id=self._connector_instance_id,
            )
        await self._join_stderr_task()
        if self._transport is not None:
            await self._transport.wait_dispatch_finished()
        self._state = ConnectorProcessState.EXITED

    async def request_shutdown(self, grace_period_seconds: int = 30) -> None:
        """Send shutdown; escalate terminate/kill if the connector stalls."""

        if self._transport is None or self._proc is None:
            return

        self._state = ConnectorProcessState.DRAINING
        try:
            await self._transport.request_shutdown(grace_period_seconds=grace_period_seconds)
        except TimeoutError:
            self._timeout_kill = True
            logger.error(
                "connector.process.shutdown_timeout",
                connector_instance_id=self._connector_instance_id,
            )
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=10.0)
            except TimeoutError:
                logger.error(
                    "connector.process.shutdown_kill",
                    connector_instance_id=self._connector_instance_id,
                )
                self._proc.kill()
                await self._proc.wait()

    async def wait(self) -> ProcessExitReason:
        """Await subprocess exit and classify the outcome."""

        if self._spawn_failed:
            return ProcessExitReason.SUBPROCESS_SPAWN_FAILED

        proc = self._proc
        if proc is None:
            return ProcessExitReason.SUBPROCESS_SPAWN_FAILED

        code = await proc.wait()
        await self._join_stderr_task()

        if self._transport is not None:
            await self._transport.wait_dispatch_finished()

        self._state = ConnectorProcessState.EXITED

        if self._hello_failed:
            return ProcessExitReason.HELLO_FAILED

        fatal = self._transport.fatal_protocol_error if self._transport is not None else None
        if fatal is not None:
            return ProcessExitReason.PROTOCOL_ERROR

        if self._timeout_kill:
            return ProcessExitReason.TIMEOUT_KILLED

        if code == 0:
            return ProcessExitReason.GRACEFUL_SHUTDOWN

        return ProcessExitReason.CRASHED
