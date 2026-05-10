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
    (
        "verbose_logger_test",
        "prow.connector.testing.verbose_logger_pkg.connector:VerboseLoggerConnector",
    ),
    (
        "metric_emitter_test",
        "prow.connector.testing.metric_emitter_pkg.connector:MetricEmitterConnector",
    ),
    (
        "stderr_chatty_test",
        "prow.connector.testing.stderr_chatty_pkg.connector:StderrChattyConnector",
    ),
    (
        "secret_logger_test",
        "prow.connector.testing.secret_logger_pkg.connector:SecretLoggerConnector",
    ),
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


def collect_secret_field_paths(schema_fragment: dict[str, Any], prefix: str = "") -> frozenset[str]:
    """Return dot-separated JSON paths for fields marked ``secret: true`` in a JSON Schema."""

    found: set[str] = set()
    props = schema_fragment.get("properties")
    if not isinstance(props, dict):
        return frozenset()
    for key, subschema in props.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(subschema, dict):
            if subschema.get("secret") is True:
                found.add(path)
            sub_type = subschema.get("type")
            nested_props = subschema.get("properties")
            if isinstance(nested_props, dict) and (sub_type == "object" or nested_props):
                found |= set(collect_secret_field_paths(subschema, path))
    return frozenset(found)


def secret_field_paths_for_entry_point(entry_point_name: str) -> frozenset[str]:
    """Secret paths derived from the connector manifest for log redaction."""

    ep = resolve_connector_entry_point(entry_point_name)
    if ep is None:
        raise ValueError(f"Unknown connector entry point {entry_point_name!r}.")
    schema = load_manifest_config_schema(ep)
    return collect_secret_field_paths(schema)


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
