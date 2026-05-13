# Copyright 2026 Prow Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from prow.connector.dev_runtime import prepare_dev_runtime
from prow.connector.entry_point_resolve import collect_secret_field_paths
from prow.connector.log_forwarder import LogForwarder
from prow.connector.metric_forwarder import MetricForwarder
from prow.connector.protocol.messages import EmitAckPayload


async def _noop_state_get(_i: str, _k: str) -> Any | None:
    return None


async def _noop_state_set(_i: str, _k: str, _v: Any) -> None:
    return


def _write_pkg(root: Path, *, bundle_suffix: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "reload-pkg"\nversion = "0"\n\n'
        '[project.entry-points."prow.connectors"]\n'
        'reload_pkg = "reload_pkg.connector:C"\n',
        encoding="utf-8",
    )
    (root / "manifest.json").write_text(
        '{"name":"reload","type":"external_import",'
        '"config_schema":{"type":"object","properties":{}}}\n',
        encoding="utf-8",
    )
    pkg = root / "reload_pkg"
    pkg.mkdir(exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "connector.py").write_text(
        "from __future__ import annotations\n"
        "from prow.connector.base import ConnectorBase\n"
        "_IND = {\n"
        '    "type": "indicator", "spec_version": "2.1",\n'
        '    "id": "indicator--8e2e2d2b-17d4-4cbf-938f-98ee46b3cd3f",\n'
        '    "created": "2024-01-01T12:00:00.000Z",\n'
        '    "modified": "2024-01-01T12:00:00.000Z",\n'
        '    "pattern": "[ipv4-addr:value = \'198.51.100.7\']",\n'
        '    "pattern_type": "stix",\n'
        '    "valid_from": "2024-01-01T12:00:00.000Z",\n'
        "}\n"
        "class C(ConnectorBase):\n"
        "    async def setup(self) -> None:\n"
        "        return\n"
        "    async def fetch(self) -> None:\n"
        "        await self.ctx.emit({\n"
        '            "type": "bundle",\n'
        f'            "id": "bundle--{bundle_suffix}",\n'
        '            "objects": [_IND],\n'
        "        })\n",
        encoding="utf-8",
    )


@pytest.mark.asyncio
@pytest.mark.slow
async def test_reload_picks_up_code_change(tmp_path: Path) -> None:
    root = tmp_path / "conn"
    _write_pkg(root, bundle_suffix="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")

    captured: list[str] = []

    async def emit_simple(_i: str, bundle: dict[str, Any]) -> EmitAckPayload:
        captured.append(str(bundle.get("id")))
        return EmitAckPayload(accepted=1, duplicates=0, validation_failures=[])

    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    secrets = collect_secret_field_paths(manifest["config_schema"])
    lf = LogForwarder("i", "reload_pkg", secrets)
    mf = MetricForwarder("i", "reload_pkg", meter=None)

    rt = prepare_dev_runtime(
        root,
        "dev",
        {},
        emit_simple,
        _noop_state_get,
        _noop_state_set,
        lf,
        mf,
        stay_alive_after_fetch=True,
    )
    await rt.start()
    for _ in range(100):
        await asyncio.sleep(0.05)
        if captured:
            break
    assert captured and captured[-1].endswith("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")

    _write_pkg(root, bundle_suffix="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    res = await rt.trigger_reload()
    assert res.success
    assert res.duration_ms < 5000, "reload took unexpectedly long on this runner"
    for _ in range(200):
        await asyncio.sleep(0.05)
        if captured and captured[-1].endswith("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"):
            break
    else:
        pytest.fail("reloaded fetch did not emit the new bundle id")

    await rt.request_shutdown()
    await rt.wait()


@pytest.mark.asyncio
@pytest.mark.slow
async def test_reload_cancels_cooperative_fetch(tmp_path: Path) -> None:
    root = tmp_path / "conn"
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "long"\nversion="0"\n\n'
        '[project.entry-points."prow.connectors"]\n'
        'long_pkg = "long_pkg.connector:C"\n',
        encoding="utf-8",
    )
    (root / "manifest.json").write_text(
        '{"name":"long","type":"external_import",'
        '"config_schema":{"type":"object","properties":{}}}\n',
        encoding="utf-8",
    )
    pkg = root / "long_pkg"
    pkg.mkdir(exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "connector.py").write_text(
        "import asyncio\n"
        "from prow.connector.base import ConnectorBase\n"
        "class C(ConnectorBase):\n"
        "    async def setup(self) -> None:\n"
        "        return\n"
        "    async def fetch(self) -> None:\n"
        "        while not self.ctx.cancelled.is_set():\n"
        "            await asyncio.sleep(0.02)\n",
        encoding="utf-8",
    )

    async def emit_simple(_i: str, _b: dict[str, Any]) -> EmitAckPayload:
        return EmitAckPayload(accepted=0, duplicates=0, validation_failures=[])

    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    secrets = collect_secret_field_paths(manifest["config_schema"])
    lf = LogForwarder("i", "long_pkg", secrets)
    mf = MetricForwarder("i", "long_pkg", meter=None)

    rt = prepare_dev_runtime(
        root,
        "dev",
        {},
        emit_simple,
        _noop_state_get,
        _noop_state_set,
        lf,
        mf,
        stay_alive_after_fetch=True,
    )
    await rt.start()
    await asyncio.sleep(0.05)
    res = await rt.trigger_reload()
    assert res.success
    await rt.request_shutdown()
    await rt.wait()


@pytest.mark.asyncio
@pytest.mark.slow
async def test_reload_failure_then_recovery(tmp_path: Path) -> None:
    root = tmp_path / "conn"
    _write_pkg(root, bundle_suffix="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")

    outs: list[str] = []

    async def emit_simple(_i: str, bundle: dict[str, Any]) -> EmitAckPayload:
        outs.append(str(bundle.get("id")))
        return EmitAckPayload(accepted=1, duplicates=0, validation_failures=[])

    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    secrets = collect_secret_field_paths(manifest["config_schema"])
    lf = LogForwarder("i", "reload_pkg", secrets)
    mf = MetricForwarder("i", "reload_pkg", meter=None)

    rt = prepare_dev_runtime(
        root,
        "dev",
        {},
        emit_simple,
        _noop_state_get,
        _noop_state_set,
        lf,
        mf,
        stay_alive_after_fetch=True,
    )
    await rt.start()
    for _ in range(100):
        await asyncio.sleep(0.05)
        if outs:
            break

    bad = root / "reload_pkg" / "connector.py"
    bad.write_text("this is not python\n", encoding="utf-8")
    bad_res = await rt.trigger_reload()
    assert bad_res.success is False
    assert bad_res.error

    _write_pkg(root, bundle_suffix="cccccccccccccccccccccccccccccccc")
    ok_res = await rt.trigger_reload()
    assert ok_res.success
    for _ in range(200):
        await asyncio.sleep(0.05)
        if outs and outs[-1].endswith("cccccccccccccccccccccccccccccccc"):
            break
    else:
        pytest.fail("recovered fetch did not emit the new bundle id")

    await rt.request_shutdown()
    await rt.wait()
