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

"""Connector authoring CLI (`prow connector …`)."""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
from pathlib import Path
from typing import Any, TextIO

import structlog
import typer

from prow.connector.base import ConnectorBase
from prow.connector.dev_emit import DevEmitHandler
from prow.connector.dev_packaging import (
    ConnectorPackageError,
    config_defaults_from_json_schema,
    discover_default_entry_name,
    ensure_connector_importable,
    find_manifest_file,
    load_manifest_document,
    validate_config_against_schema,
    validate_manifest_shape,
)
from prow.connector.dev_runtime import ReloadResult, prepare_dev_runtime
from prow.connector.dev_watcher import DevWatcher
from prow.connector.entry_point_resolve import (
    collect_secret_field_paths,
    resolve_connector_entry_point,
)
from prow.connector.log_forwarder import LogForwarder
from prow.connector.metric_forwarder import MetricForwarder
from prow.connector.protocol.messages import MetricPayload

app = typer.Typer(no_args_is_help=True)

_ISSUE_STUB = "Pass D — tracked as prow-cti#connector-http-fixture-replay"

_WARN_SIDE_EFFECTS_BANNER = (
    "Hot reload hint: duplicate singletons or stale globals after save often mean "
    "import-time side effects (network calls, threads, mutations at import time)."
)


class DevCliMetricForwarder(MetricForwarder):
    """Print metric payloads to stderr instead of OpenTelemetry (no meter required)."""

    def forward(self, payload: MetricPayload) -> None:
        sys.stderr.write(
            "[dev metric] "
            f"name={payload.name!s} value={payload.value!s} "
            f"unit={payload.unit!r} tags={payload.tags!r}\n",
        )


async def _async_dev(
    connector_path: Path,
    config_file: Path | None,
    instance_id: str,
    no_watch: bool,
    *,
    stdout: TextIO,
    stderr: TextIO,
) -> None:
    manifest_path = find_manifest_file(connector_path)
    manifest = load_manifest_document(manifest_path)
    validate_manifest_shape(manifest, path=manifest_path)
    if manifest.get("type") != "external_import":
        typer.echo(
            f"Dev mode supports type=external_import only (manifest has {manifest.get('type')!r}).",
            err=True,
        )
        raise typer.Exit(code=1)

    cfg_schema = manifest["config_schema"]
    if not isinstance(cfg_schema, dict):
        typer.echo("manifest.config_schema must be an object.", err=True)
        raise typer.Exit(code=1)

    defaults = config_defaults_from_json_schema(cfg_schema)
    config_data = dict(defaults)
    if config_file is not None:
        extra = json.loads(config_file.read_text(encoding="utf-8"))
        if not isinstance(extra, dict):
            typer.echo("--config must contain a JSON object.", err=True)
            raise typer.Exit(code=1)
        config_data.update(extra)

    try:
        validate_config_against_schema(cfg_schema, config_data)
    except ConnectorPackageError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    entry_name, _entry_target = discover_default_entry_name(connector_path)
    secrets = collect_secret_field_paths(cfg_schema)

    emit = DevEmitHandler(stream=stdout)
    state_bag: dict[str, Any] = {}

    async def state_get(_i: str, key: str) -> Any | None:
        return state_bag.get(key)

    async def state_set(_i: str, key: str, value: Any) -> None:
        state_bag[key] = value

    log_fw = LogForwarder(
        instance_id,
        entry_name,
        secrets,
        logger=structlog.get_logger("prow.connector"),
    )
    metric_fw = DevCliMetricForwarder(instance_id, entry_name)

    runtime = prepare_dev_runtime(
        connector_path,
        instance_id,
        config_data,
        emit,
        state_get,
        state_set,
        log_fw,
        metric_fw,
        shared_state_store=state_bag,
        stay_alive_after_fetch=not no_watch,
    )

    typer.echo(
        f"Prow connector dev — {manifest.get('name')!r} @ {connector_path}\n"
        f"Manifest: {manifest_path}\n"
        f"Entry: {entry_name}\n"
        f"{_WARN_SIDE_EFFECTS_BANNER}\n",
        file=stderr,
    )

    watcher: DevWatcher | None = None

    async def on_change(paths: set[Path]) -> None:
        typer.echo(f"[reload] detected change in {len(paths)} path(s)", file=stderr)
        result = await runtime.trigger_reload()
        _print_reload(result, stderr)

    if not no_watch:
        watcher = DevWatcher(connector_path, on_change)
        await watcher.start()

    await runtime.start()

    try:
        await runtime.wait()
    except asyncio.CancelledError:
        raise
    finally:
        await runtime.request_shutdown()
        if watcher is not None:
            await watcher.stop()


def _print_reload(result: ReloadResult, stream: TextIO = sys.stderr) -> None:
    status = "ok" if result.success else "failed"
    typer.echo(
        f"[reload] {status} in {result.duration_ms}ms",
        file=stream,
    )
    if result.warning:
        typer.echo(f"[reload] warning: {result.warning}", file=stream)
    if result.error:
        typer.echo(f"[reload] error: {result.error}", file=stream)


@app.command("dev")
def dev_command(
    path: Path = typer.Argument(..., help="Path to connector package"),
    config_file: Path | None = typer.Option(
        None,
        "--config",
        help="JSON file with connector config; defaults to manifest defaults",
    ),
    instance_id: str = typer.Option("dev", help="Instance ID for log binding"),
    no_watch: bool = typer.Option(False, "--no-watch", help="Run once without hot-reload"),
) -> None:
    """Run a connector in-process with optional filesystem hot reload."""

    async def _runner() -> None:
        await _async_dev(
            path.resolve(),
            config_file.resolve() if config_file else None,
            instance_id,
            no_watch,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )

    try:
        asyncio.run(_runner())
    except KeyboardInterrupt:
        typer.echo("\n[dev] shutdown", err=True)


@app.command("test")
def test_command(
    path: Path = typer.Argument(..., help="Path to connector package"),
    fixture: Path = typer.Option(
        ...,
        "--fixture",
        help="Recorded HTTP fixture for offline testing",
    ),
) -> None:
    """Offline connector tests against recorded HTTP fixtures (not yet implemented)."""

    del path, fixture
    typer.echo(
        f"Fixture replay is not yet implemented; see {_ISSUE_STUB}.",
        err=True,
    )
    raise typer.Exit(code=1)


@app.command("validate")
def validate_command(path: Path = typer.Argument(..., help="Path to connector package")) -> None:
    """Validate manifest schema and connector entry point resolution."""

    root = path.resolve()
    try:
        manifest_path = find_manifest_file(root)
        manifest = load_manifest_document(manifest_path)
        validate_manifest_shape(manifest, path=manifest_path)
        entry_name, target = discover_default_entry_name(root)
        mod_part, _, attr = target.partition(":")
        ensure_connector_importable(root, mod_part)
        ep = resolve_connector_entry_point(entry_name)
        if ep is not None:
            loaded = ep.load()
        else:
            mod = importlib.import_module(mod_part)
            loaded = getattr(mod, attr)
        if not isinstance(loaded, type) or not issubclass(loaded, ConnectorBase):
            typer.echo(f"Resolved loader returned non-connector type: {loaded!r}", err=True)
            raise typer.Exit(code=1)
        typer.echo(
            f"OK — manifest {manifest_path}\n"
            f"Entry {entry_name} -> {target}\n"
            f"Loaded class: {loaded!r}",
        )
    except ConnectorPackageError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        typer.echo(f"{type(exc).__name__}: {exc}", err=True)
        raise typer.Exit(code=1) from exc
