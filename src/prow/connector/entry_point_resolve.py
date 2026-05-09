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

"""Resolve prow connector entry points and validate instance config (manifest schema)."""

from __future__ import annotations

import json
from importlib import import_module
from importlib.metadata import EntryPoint, entry_points
from pathlib import Path
from typing import Any

import jsonschema
from jsonschema import ValidationError as JsonSchemaValidationError

# Bundled fallbacks match ``pyproject.toml`` entry-points and
# ``prow.connector.runner._BUNDLED_TEST_ENTRY_POINTS``.
_BUNDLED_CONNECTOR_ENTRY_POINTS: tuple[tuple[str, str], ...] = (
    ("lifecycle_test", "prow.connector.testing.lifecycle_pkg.connector:LifecycleConnector"),
    ("hang_test", "prow.connector.testing.hang_pkg.connector:HangConnector"),
    ("crash_test", "prow.connector.testing.crash_pkg.connector:CrashConnector"),
    ("minimal_test", "prow.connector.testing.minimal_pkg.connector:MinimalConnector"),
    ("crash_setup_test", "prow.connector.testing.crash_setup_pkg.connector:CrashSetupConnector"),
    ("slow_health_test", "prow.connector.testing.slow_health_pkg.connector:SlowHealthConnector"),
)


def resolve_connector_entry_point(entry_name: str) -> EntryPoint | None:
    """Resolve an entry point, preferring bundled fallbacks (fast, no metadata scan)."""

    for name, target in _BUNDLED_CONNECTOR_ENTRY_POINTS:
        if name == entry_name:
            return EntryPoint(name=name, value=target, group="prow.connectors")
    for ep in entry_points(group="prow.connectors"):
        if ep.name == entry_name:
            return ep
    return None


def load_manifest_config_schema(ep: EntryPoint) -> dict[str, Any]:
    """Load ``manifest.json`` config_schema adjacent to the connector module."""

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


def validate_config_dict(schema: dict[str, Any], config: dict[str, Any]) -> None:
    jsonschema.validate(instance=config, schema=schema)


def validate_connector_instance_config(entry_point_name: str, config: dict[str, Any]) -> None:
    """Validate *config* against the connector manifest schema for *entry_point_name*."""

    ep = resolve_connector_entry_point(entry_point_name)
    if ep is None:
        raise ValueError(f"Unknown connector entry point {entry_point_name!r}.")
    schema = load_manifest_config_schema(ep)
    try:
        validate_config_dict(schema, config)
    except JsonSchemaValidationError as exc:
        msg = f"Instance config failed validation for {entry_point_name!r}: {exc.message}"
        raise ValueError(msg) from exc
