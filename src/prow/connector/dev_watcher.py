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

"""Filesystem watcher for connector hot reload (debounced)."""

from __future__ import annotations

import asyncio
import fnmatch
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import structlog
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

logger = structlog.get_logger(__name__)

OnChange = Callable[[set[Path]], Awaitable[None]]


def _should_ignore(rel: Path, ignore_patterns: tuple[str, ...]) -> bool:
    parts = rel.parts
    for part in parts:
        for pat in ignore_patterns:
            if fnmatch.fnmatch(part, pat):
                return True
    name = rel.as_posix()
    for pat in ignore_patterns:
        if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(rel.name, pat):
            return True
    return False


class DevWatcher:
    """Watches ``*.py`` under *path* with debounced async callbacks."""

    def __init__(
        self,
        path: Path,
        on_change: OnChange,
        debounce_ms: int = 200,
        ignore_patterns: tuple[str, ...] = (
            "*.pyc",
            "__pycache__",
            ".git",
            ".pytest_cache",
            "*.egg-info",
            ".venv",
            "venv",
        ),
        *,
        force_polling: bool = False,
    ) -> None:
        self._root = path.resolve()
        self._on_change = on_change
        self._debounce_ms = debounce_ms
        self._ignore_patterns = ignore_patterns
        self._force_polling = force_polling

        self._loop: asyncio.AbstractEventLoop | None = None
        self._debounced: _DebouncedAsyncCallback | None = None
        self._observer: Any = None

    async def start(self) -> None:
        if self._observer is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError as exc:
            msg = "DevWatcher.start() requires a running asyncio loop"
            raise RuntimeError(msg) from exc

        self._loop = loop
        self._debounced = _DebouncedAsyncCallback(loop, self._debounce_ms, self._on_change)

        handler = _WatchdogBridge(self._root, self._ignore_patterns, self._debounced)

        observer: Any
        if self._force_polling:
            observer = PollingObserver()
        else:
            observer = Observer()
        observer.schedule(handler, str(self._root), recursive=True)
        observer.start()

        self._observer = observer
        logger.info(
            "connector.dev_watcher.started",
            path=str(self._root),
            polling=self._force_polling,
        )

    async def stop(self) -> None:
        obs = self._observer
        self._observer = None
        if obs is not None:
            obs.stop()
            obs.join(timeout=5.0)
            if obs.is_alive():
                logger.warning("connector.dev_watcher.join_timeout")
        self._debounced = None
        self._loop = None


class _DebouncedAsyncCallback:
    """Accumulates paths on the event-loop thread; fires one callback per burst."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        debounce_ms: int,
        on_change: OnChange,
    ) -> None:
        self._loop = loop
        self._debounce_ms = debounce_ms
        self._on_change = on_change
        self._paths: set[Path] = set()
        self._handle: asyncio.TimerHandle | None = None
        self._emit_task: asyncio.Task[None] | None = None

    def push(self, path: Path) -> None:
        # Watchdog delivers events on the observer thread; schedule debounce on the loop thread.
        self._loop.call_soon_threadsafe(self._enqueue, path)

    def _enqueue(self, path: Path) -> None:
        self._paths.add(path)
        if self._handle is not None:
            self._handle.cancel()
        self._handle = self._loop.call_later(self._debounce_ms / 1000.0, self._on_timer)

    def _on_timer(self) -> None:
        self._emit_task = asyncio.create_task(self._emit(), name="dev-watcher-debounced")

    async def _emit(self) -> None:
        self._handle = None
        if not self._paths:
            return
        batch = self._paths
        self._paths = set()
        await self._on_change(batch)


class _WatchdogBridge(FileSystemEventHandler):
    def __init__(
        self,
        root: Path,
        ignore_patterns: tuple[str, ...],
        debounced: _DebouncedAsyncCallback,
    ) -> None:
        super().__init__()
        self._root = root
        self._ignore_patterns = ignore_patterns
        self._debounced = debounced

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        raw = event.src_path
        src_norm = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        path = Path(src_norm)
        try:
            rel = path.resolve().relative_to(self._root)
        except ValueError:
            rel = path
        if path.suffix.lower() != ".py":
            return
        if _should_ignore(rel, self._ignore_patterns):
            return
        self._debounced.push(path.resolve())
