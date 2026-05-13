# Copyright 2026 Prow Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from prow.connector.dev_watcher import DevWatcher


@pytest.mark.asyncio
@pytest.mark.slow
async def test_watcher_fires_on_py_change(tmp_path: Path) -> None:
    fired: asyncio.Future[set[Path]] = asyncio.get_running_loop().create_future()
    hits: list[set[Path]] = []

    async def on_change(paths: set[Path]) -> None:
        hits.append(set(paths))
        if not fired.done():
            fired.set_result(paths)

    base = tmp_path.resolve()
    root = base / "pkg"
    root.mkdir(parents=True)
    root = root.resolve()
    target = root / "mod.py"
    target.write_text("x = 1\n", encoding="utf-8")

    w = DevWatcher(root, on_change, debounce_ms=50, force_polling=True)
    await w.start()
    # PollingObserver diffs snapshots ~1s apart; wait one interval so the baseline
    # includes x=1 before we write x=2 (avoids a race where the first snapshot is
    # already post-mutation and no change is detected).
    await asyncio.sleep(1.2)
    target.write_text("x = 2\n", encoding="utf-8")
    paths = await asyncio.wait_for(fired, timeout=10.0)
    assert paths
    await w.stop()


@pytest.mark.asyncio
@pytest.mark.slow
async def test_watcher_debounces_burst(tmp_path: Path) -> None:
    events: list[set[Path]] = []

    async def on_change(paths: set[Path]) -> None:
        events.append(set(paths))

    base = tmp_path.resolve()
    root = base / "pkg"
    root.mkdir(parents=True)
    root = root.resolve()
    files = [root / f"f{i}.py" for i in range(5)]
    for f in files:
        f.write_text("#\n", encoding="utf-8")

    w = DevWatcher(root, on_change, debounce_ms=80, force_polling=True)
    await w.start()
    start = time.perf_counter()
    for f in files:
        f.write_text("# touch\n", encoding="utf-8")
        await asyncio.sleep(0.01)
    burst_ms = (time.perf_counter() - start) * 1000
    assert burst_ms < 600
    await asyncio.sleep(0.15)
    # PollingObserver polls about once per second; allow a cycle after the burst so
    # events are observed before we stop the watcher.
    await asyncio.sleep(1.2)
    await w.stop()
    assert len(events) >= 1
    assert set.union(*events) == {f.resolve() for f in files}


@pytest.mark.asyncio
@pytest.mark.slow
async def test_watcher_ignores_pyc(tmp_path: Path) -> None:
    fired = asyncio.Event()

    async def on_change(_paths: set[Path]) -> None:
        fired.set()

    base = tmp_path.resolve()
    root = base / "pkg"
    root.mkdir(parents=True)
    root = root.resolve()
    (root / "a.py").write_text("x=1\n", encoding="utf-8")
    cache = root / "__pycache__"
    cache.mkdir()
    pyc = cache / "x.pyc"
    pyc.write_bytes(b"\x00")

    w = DevWatcher(root, on_change, debounce_ms=30, force_polling=True)
    await w.start()
    pyc.write_bytes(b"\x01\x02")
    await asyncio.sleep(0.15)
    await w.stop()
    assert not fired.is_set()


@pytest.mark.asyncio
@pytest.mark.slow
async def test_watcher_stop_prevents_further_events(tmp_path: Path) -> None:
    fired_after_stop = asyncio.Event()

    async def on_change(_paths: set[Path]) -> None:
        fired_after_stop.set()

    base = tmp_path.resolve()
    root = base / "pkg"
    root.mkdir(parents=True)
    root = root.resolve()
    f = root / "m.py"
    f.write_text("a=1\n", encoding="utf-8")

    w = DevWatcher(root, on_change, debounce_ms=40, force_polling=True)
    await w.start()
    await w.stop()
    f.write_text("a=2\n", encoding="utf-8")
    await asyncio.sleep(0.2)
    assert not fired_after_stop.is_set()


@pytest.mark.asyncio
@pytest.mark.slow
async def test_polling_observer_smoke(tmp_path: Path) -> None:
    fired: asyncio.Future[None] = asyncio.get_running_loop().create_future()

    async def on_change(_paths: set[Path]) -> None:
        if not fired.done():
            fired.set_result(None)

    base = tmp_path.resolve()
    root = base / "pkg"
    root.mkdir(parents=True)
    root = root.resolve()
    f = root / "z.py"
    f.write_text("z=1\n", encoding="utf-8")

    w = DevWatcher(root, on_change, debounce_ms=40, force_polling=True)
    await w.start()
    await asyncio.sleep(1.2)
    f.write_text("z=2\n", encoding="utf-8")
    await asyncio.wait_for(fired, timeout=10.0)
    await w.stop()
