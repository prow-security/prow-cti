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

"""Connector subprocess entry point (protocol on stdout; stderr for logs)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from importlib import import_module
from importlib.metadata import EntryPoint, entry_points
from pathlib import Path
from typing import Any

import jsonschema
import structlog
from jsonschema import ValidationError as JsonSchemaValidationError

from prow.connector.base import ConnectorBase
from prow.connector.pipe_stdio import connector_subprocess_exit, open_connector_stdio_streams
from prow.connector.protocol.codec import ProtocolError
from prow.connector.protocol.messages import LogLevel
from prow.connector.protocol.negotiation import DEFAULT_SUPPORTED_VERSIONS, perform_hello_connector

# Bundled under ``prow.connector.testing`` for automated tests; also listed in
# ``pyproject.toml`` so ``pip install`` registers them. When the package is run
# from a source checkout without installed metadata, fall back to this table.
_BUNDLED_TEST_ENTRY_POINTS: tuple[tuple[str, str], ...] = (
    ("lifecycle_test", "prow.connector.testing.lifecycle_pkg.connector:LifecycleConnector"),
    ("hang_test", "prow.connector.testing.hang_pkg.connector:HangConnector"),
    ("crash_test", "prow.connector.testing.crash_pkg.connector:CrashConnector"),
    ("minimal_test", "prow.connector.testing.minimal_pkg.connector:MinimalConnector"),
)


def _resolve_connector_entry_point(entry_name: str) -> EntryPoint | None:
    """Resolve an entry point, preferring bundled fallbacks (fast, no metadata scan)."""

    for name, target in _BUNDLED_TEST_ENTRY_POINTS:
        if name == entry_name:
            return EntryPoint(name=name, value=target, group="prow.connectors")
    for ep in entry_points(group="prow.connectors"):
        if ep.name == entry_name:
            return ep
    return None


def _configure_stderr_logging(instance_id: str) -> None:
    """Emit structured logs to stderr (stdout is reserved for JSONL)."""

    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        stream=sys.stderr,
        force=True,
    )
    logging.getLogger("prow.stix").setLevel(logging.WARNING)
    logging.getLogger("stix").setLevel(logging.WARNING)

    structlog.reset_defaults()
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )
    structlog.contextvars.bind_contextvars(connector_instance_id=instance_id)


def _runtime_connector_version() -> str:
    try:
        from importlib.metadata import version

        return version("prow")
    except Exception:
        return "0.0.0"


def _load_manifest_schema(ep: EntryPoint) -> dict[str, Any]:
    """Load ``manifest.json`` adjacent to the connector module (Pass C1 JSON bundle)."""

    module = import_module(ep.module)
    if module.__file__ is None:
        raise FileNotFoundError("Connector module has no __file__ path.")
    root = Path(module.__file__).resolve().parent
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"manifest.json not found next to connector module ({manifest_path}).",
        )
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw_schema = data.get("config_schema")
    if raw_schema is None:
        raise ValueError("manifest.json must contain a config_schema object.")
    if not isinstance(raw_schema, dict):
        raise ValueError("manifest.json config_schema must be a JSON object.")
    return raw_schema


def _validate_config(schema: dict[str, Any], config: dict[str, Any]) -> None:
    jsonschema.validate(instance=config, schema=schema)


def _load_connector_class(ep: EntryPoint) -> type[ConnectorBase]:
    loaded = ep.load()
    if not isinstance(loaded, type) or not issubclass(loaded, ConnectorBase):
        raise TypeError("Connector entry point must resolve to a ConnectorBase subclass.")
    return loaded


async def _async_main() -> None:
    """Run connector lifecycle; always ends via :func:`connector_subprocess_exit`.

    On Windows the stdin pump uses ``asyncio.to_thread``; ending with a normal
    return would let ``asyncio.run`` shut down the loop while that worker can
    still be blocked on ``readline``, so we exit the interpreter from inside the
    coroutine (see ``pipe_stdio.connector_subprocess_exit``).
    """

    instance_id = os.environ.get("PROW_CONNECTOR_INSTANCE_ID")
    entry_name = os.environ.get("PROW_CONNECTOR_ENTRY_POINT")
    if not instance_id or not entry_name:
        sys.stderr.write("Missing PROW_CONNECTOR_INSTANCE_ID or PROW_CONNECTOR_ENTRY_POINT.\n")
        connector_subprocess_exit(2)

    _configure_stderr_logging(instance_id)

    # Attach protocol streams before importing STIX (context/types pull validators that log).
    reader, writer = await open_connector_stdio_streams()

    ep_named = _resolve_connector_entry_point(entry_name)
    if ep_named is None:
        sys.stderr.write(f"Unknown connector entry point {entry_name!r}.\n")
        connector_subprocess_exit(2)

    try:
        agreed_version, raw_config = await perform_hello_connector(
            reader,
            writer,
            connector_version=_runtime_connector_version(),
            supported_versions=DEFAULT_SUPPORTED_VERSIONS,
            timeout_seconds=30.0,
        )
    except ProtocolError as exc:
        sys.stderr.write(f"Hello negotiation failed: {exc.message}\n")
        connector_subprocess_exit(3)

    from prow.connector.context import ConnectorContext
    from prow.connector.transport_stdio import StdioTransport

    try:
        schema = _load_manifest_schema(ep_named)
        _validate_config(schema, raw_config)
    except (FileNotFoundError, ValueError, JsonSchemaValidationError) as exc:
        sys.stderr.write(f"Config validation failed: {exc}\n")
        connector_subprocess_exit(4)

    transport = StdioTransport(instance_id, reader, writer, agreed_version)
    ctx = ConnectorContext(transport, raw_config)

    await transport.log(
        LogLevel.INFO,
        "connector.runner.ready",
        fields={"protocol_version": agreed_version},
        exception=None,
    )

    connector_cls = _load_connector_class(ep_named)
    connector = connector_cls(ctx)

    try:
        await connector.setup()
        await ctx.cancelled.wait()
        await connector.teardown()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        sys.stderr.write(f"Connector raised: {exc!r}\n")
        connector_subprocess_exit(5)
    finally:
        dt = getattr(transport, "_dispatch_task", None)
        if dt is not None and not dt.done():
            dt.cancel()

    connector_subprocess_exit(0)


def main() -> None:
    """Blocking entry used by ``python -c 'from prow.connector.runner import main; main()'``."""

    try:
        asyncio.run(_async_main())
    except KeyboardInterrupt:
        connector_subprocess_exit(130)
