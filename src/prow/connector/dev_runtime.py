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

"""In-process dev runtime with hot reload (Pass D)."""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from typing import Any

import structlog

from prow.connector.base import ConnectorBase
from prow.connector.context import ConnectorContext
from prow.connector.dev_packaging import (
    ConnectorPackageError,
    discover_default_entry_name,
    ensure_connector_importable,
    find_manifest_file,
    load_manifest_document,
    validate_manifest_shape,
)
from prow.connector.log_forwarder import LogForwarder
from prow.connector.metric_forwarder import MetricForwarder
from prow.connector.protocol.messages import EmitAckPayload
from prow.connector.transport_inprocess import InProcessTransport

EmitHandler = Callable[[str, dict[str, Any]], Awaitable[EmitAckPayload]]
StateGetHandler = Callable[[str, str], Awaitable[Any | None]]
StateSetHandler = Callable[[str, str, Any], Awaitable[None]]

logger = structlog.get_logger(__name__)

_RELOAD_COOPERATE_TIMEOUT_S = 3.0

_WARN_METACLASS = (
    "Reload warning: connector class identity changed across reload. "
    "Metaclasses and __init_subclass__ can leave stale class objects — "
    "prefer plain classes for hot-reload-friendly connectors."
)

_WARN_EXTENSION = (
    "Reload warning: this connector package loads native compiled extensions "
    "(.so/.pyd). Python cannot replace C-level state on reload — "
    "restart `prow connector dev` after changing native code."
)

_WARN_IMPORT_SIDE_EFFECTS = (
    "Reload hint: if you see duplicate singletons or stale globals after save, "
    "check for import-time side effects (network calls, threads, mutations at import)."
)


@dataclass(frozen=True)
class ReloadResult:
    """Outcome of one hot-reload attempt."""

    success: bool
    duration_ms: int
    error: str | None
    warning: str | None


def _eviction_prefix_for_module(module_name: str) -> str:
    """Return dotted prefix to drop from ``sys.modules`` before re-import.

    Evicts the containing package tree (parent of the leaf module), e.g.
    ``prow.connector.testing.minimal_pkg.connector`` →
    ``prow.connector.testing.minimal_pkg``, and ``spam`` → ``spam``.
    """

    parts = module_name.split(".")
    if len(parts) == 1:
        return parts[0]
    return ".".join(parts[:-1])


def _purge_bytecode_under(root: Path) -> None:
    """Remove ``*.pyc`` so Windows/Linux don't reuse bytecode across reloads."""

    try:
        for cache in root.rglob("__pycache__"):
            if not cache.is_dir():
                continue
            for child in list(cache.iterdir()):
                if child.suffix == ".pyc":
                    try:
                        child.unlink()
                    except OSError:
                        logger.warning("connector.dev.unlink_bytecode_failed", path=str(child))
    except OSError as exc:
        logger.warning("connector.dev.purge_bytecode_failed", error=str(exc))


def _evict_package_modules(package_prefix: str) -> None:
    keys = [k for k in sys.modules if k == package_prefix or k.startswith(f"{package_prefix}.")]
    for k in keys:
        del sys.modules[k]


def _compiled_extension_warning_for_module(module_name: str) -> str | None:
    spec = find_spec(module_name)
    if spec is None or not spec.origin:
        return None
    origin = spec.origin.lower()
    if origin.endswith((".so", ".pyd")):
        return _WARN_EXTENSION
    return None


class DevRuntime:
    """Runs a connector in-process with hot reload."""

    def __init__(
        self,
        connector_path: Path,
        instance_id: str,
        config: dict[str, Any],
        emit_handler: EmitHandler,
        state_get_handler: StateGetHandler,
        state_set_handler: StateSetHandler,
        log_forwarder: LogForwarder,
        metric_forwarder: MetricForwarder,
        *,
        manifest: dict[str, Any],
        entry_name: str,
        entry_target: str,
        shared_state_store: dict[str, Any] | None = None,
        stay_alive_after_fetch: bool = True,
    ) -> None:
        self._connector_path = connector_path.resolve()
        self._instance_id = instance_id
        self._config = config
        self._user_emit = emit_handler
        self._state_get = state_get_handler
        self._state_set = state_set_handler
        self._log_forwarder = log_forwarder
        self._metric_forwarder = metric_forwarder
        self._manifest = manifest
        self._entry_target = entry_target

        self._state_store: dict[str, Any] = (
            shared_state_store if shared_state_store is not None else {}
        )
        self._main_logger = structlog.get_logger("prow.connector.dev").bind(entry_name=entry_name)

        self._connector: ConnectorBase | None = None
        self._transport: InProcessTransport | None = None
        self._ctx: ConnectorContext | None = None
        self._fetch_task: asyncio.Task[None] | None = None

        self._shutdown = asyncio.Event()
        self._run_task: asyncio.Task[None] | None = None
        self._reload_lock = asyncio.Lock()
        self._stay_alive_after_fetch = stay_alive_after_fetch

    async def start(self) -> None:
        """Load connector, ``setup``, ``fetch``, then idle until reload/shutdown."""

        if self._run_task is not None:
            return
        self._run_task = asyncio.create_task(self._run_loop(), name="dev-runtime-loop")

    async def wait(self) -> None:
        if self._run_task is None:
            return
        await self._run_task

    async def request_shutdown(self) -> None:
        self._shutdown.set()
        if self._transport is not None:
            await self._transport.shutdown()
        if self._fetch_task is not None and not self._fetch_task.done():
            self._fetch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._fetch_task
        if self._connector is not None:
            with contextlib.suppress(Exception):
                await self._connector.teardown()

    async def trigger_reload(self) -> ReloadResult:
        async with self._reload_lock:
            return await self._reload_impl()

    async def _run_loop(self) -> None:
        try:
            await self._initial_mount_and_fetch()
            if not self._stay_alive_after_fetch:
                return
            await self._shutdown.wait()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("connector.dev_runtime.fatal", error=str(exc))
            raise
        finally:
            await self._cleanup_connector()

    async def _initial_mount_and_fetch(self) -> None:
        self._transport = self._make_transport()
        await self._mount_connector(await self._import_connector_class())
        self._start_fetch_task()
        if not self._stay_alive_after_fetch:
            await self._join_fetch_task()

    def _make_transport(self) -> InProcessTransport:
        async def emit(bundle: dict[str, Any]) -> EmitAckPayload:
            return await self._user_emit(self._instance_id, bundle)

        return InProcessTransport(
            self._instance_id,
            emit,
            self._state_store,
            self._main_logger,
            meter=None,
            log_forwarder=self._log_forwarder,
            metric_forwarder=self._metric_forwarder,
        )

    async def _import_connector_class(self) -> type[ConnectorBase]:
        ensure_connector_importable(self._connector_path, self._entry_target.split(":")[0])
        # Always import via ``pyproject.toml`` target after ``sys.modules`` eviction.
        # ``importlib.metadata.EntryPoint.load()`` can retain stale class objects across reload.
        loaded = self._fallback_import_class()
        if not isinstance(loaded, type) or not issubclass(loaded, ConnectorBase):
            raise TypeError(
                f"Connector entry must resolve to ConnectorBase subclass, got {loaded!r}",
            )
        warn = _compiled_extension_warning_for_module(loaded.__module__)
        if warn:
            logger.warning(warn)
        return loaded

    def _fallback_import_class(self) -> type[Any]:
        mod_part, _, attr = self._entry_target.partition(":")
        if not attr:
            raise ConnectorPackageError(
                f"Invalid entry target {self._entry_target!r}. Install the package with "
                "`pip install -e .` from the connector directory, or fix pyproject.toml.",
            )
        try:
            mod = importlib.import_module(mod_part)
        except ImportError as exc:
            raise ConnectorPackageError(
                "Could not import connector module. Install the package in editable mode "
                f"(`pip install -e .` in {self._connector_path}) so entry points resolve.",
            ) from exc
        cls_obj = getattr(mod, attr)
        if not isinstance(cls_obj, type):
            raise ConnectorPackageError(f"Entry attribute {attr!r} is not a class.")
        return cls_obj

    async def _mount_connector(self, cls: type[ConnectorBase]) -> None:
        if self._transport is None:
            self._transport = self._make_transport()
        ctx = ConnectorContext(self._transport, self._config)
        self._ctx = ctx
        self._connector = cls(ctx)
        await self._connector.setup()

    def _start_fetch_task(self) -> None:
        conn = self._connector
        if conn is None:
            msg = "connector is not mounted"
            raise RuntimeError(msg)
        if not hasattr(conn, "fetch"):
            raise TypeError("external_import connectors must define async def fetch(self).")

        async def _runner() -> None:
            await conn.fetch()

        self._fetch_task = asyncio.create_task(_runner(), name="dev-fetch")

    async def _join_fetch_task(self) -> None:
        if self._fetch_task is None:
            return
        try:
            await self._fetch_task
        finally:
            self._fetch_task = None

    async def _reload_impl(self) -> ReloadResult:
        t0 = time.perf_counter()
        warning: str | None = None
        try:
            if self._transport is not None:
                self._transport.cancelled.set()
            if self._fetch_task is not None and not self._fetch_task.done():
                try:
                    await asyncio.wait_for(self._fetch_task, timeout=_RELOAD_COOPERATE_TIMEOUT_S)
                except TimeoutError:
                    logger.warning(
                        "connector.dev.reload_fetch_timeout",
                        timeout_s=_RELOAD_COOPERATE_TIMEOUT_S,
                    )
                    self._fetch_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await self._fetch_task
                except asyncio.CancelledError:
                    pass

            if self._connector is not None:
                await self._connector.teardown()

            prefix = _eviction_prefix_for_module(self._entry_target.split(":")[0])
            _evict_package_modules(prefix)
            importlib.invalidate_caches()
            _purge_bytecode_under(self._connector_path)

            new_cls = await self._import_connector_class()
            if type(new_cls) is not type:
                warning = _WARN_METACLASS

            self._transport = self._make_transport()
            await self._mount_connector(new_cls)
            self._start_fetch_task()

            dt_ms = int((time.perf_counter() - t0) * 1000)
            return ReloadResult(success=True, duration_ms=dt_ms, error=None, warning=warning)
        except Exception as exc:
            dt_ms = int((time.perf_counter() - t0) * 1000)
            logger.exception("connector.dev.reload_failed", error=str(exc))
            if self._connector is not None:
                with contextlib.suppress(Exception):
                    await self._connector.teardown()
            self._connector = None
            self._transport = None
            return ReloadResult(
                success=False,
                duration_ms=dt_ms,
                error=f"{type(exc).__name__}: {exc}",
                warning=None,
            )

    async def _cleanup_connector(self) -> None:
        if self._connector is not None:
            with contextlib.suppress(Exception):
                await self._connector.teardown()
        self._connector = None


def prepare_dev_runtime(
    connector_path: Path,
    instance_id: str,
    config: dict[str, Any],
    emit_handler: EmitHandler,
    state_get_handler: StateGetHandler,
    state_set_handler: StateSetHandler,
    log_forwarder: LogForwarder,
    metric_forwarder: MetricForwarder,
    *,
    shared_state_store: dict[str, Any] | None = None,
    stay_alive_after_fetch: bool = True,
) -> DevRuntime:
    """Discover manifest/entry point and construct :class:`DevRuntime`."""

    manifest_path = find_manifest_file(connector_path)
    manifest = load_manifest_document(manifest_path)
    validate_manifest_shape(manifest, path=manifest_path)
    if manifest.get("type") != "external_import":
        raise ConnectorPackageError(
            "Dev runtime supports type=external_import only "
            f"(manifest has {manifest.get('type')!r}).",
        )
    entry_name, entry_target = discover_default_entry_name(connector_path)
    return DevRuntime(
        connector_path,
        instance_id,
        config,
        emit_handler,
        state_get_handler,
        state_set_handler,
        log_forwarder,
        metric_forwarder,
        manifest=manifest,
        entry_name=entry_name,
        entry_target=entry_target,
        shared_state_store=shared_state_store,
        stay_alive_after_fetch=stay_alive_after_fetch,
    )
