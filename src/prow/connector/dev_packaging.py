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

"""Discover connector packages on disk for dev and validate CLI (Pass D)."""

from __future__ import annotations

import json
import sys
import tomllib
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Any

import jsonschema
from jsonschema import ValidationError as JsonSchemaValidationError


class ConnectorPackageError(ValueError):
    """Failed to read or interpret a connector package directory."""


def find_manifest_file(connector_root: Path) -> Path:
    """Return ``manifest.json`` or ``manifest.yaml`` under *connector_root* or ``src/*``."""

    for name in ("manifest.json", "manifest.yaml"):
        direct = connector_root / name
        if direct.is_file():
            return direct
    for child in connector_root.iterdir():
        if child.is_dir() and child.name not in {"__pycache__", ".git", "venv", ".venv"}:
            for name in ("manifest.json", "manifest.yaml"):
                p = child / name
                if p.is_file():
                    return p
    raise ConnectorPackageError(
        f"No manifest.json or manifest.yaml found under {connector_root}.",
    )


def load_manifest_document(path: Path) -> dict[str, Any]:
    """Load connector manifest (JSON or YAML subset without PyYAML for ``.yaml``)."""

    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".json"}:
        data = json.loads(text)
    elif path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ConnectorPackageError(
                "Install PyYAML to load manifest.yaml files, or use manifest.json.",
            ) from exc
        data = yaml.safe_load(text)
    else:
        raise ConnectorPackageError(f"Unsupported manifest extension: {path.suffix}")
    if not isinstance(data, dict):
        raise ConnectorPackageError("Manifest root must be a JSON object.")
    return data


def parse_pyproject_connector_entry_points(pyproject_path: Path) -> dict[str, str]:
    """Return ``{entry_name -> 'module.path:Class'}`` for ``prow.connectors``."""

    raw = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project = raw.get("project")
    if not isinstance(project, dict):
        return {}
    eps = project.get("entry-points")
    if not isinstance(eps, dict):
        return {}
    group = eps.get("prow.connectors")
    if not isinstance(group, dict):
        return {}
    out: dict[str, str] = {}
    for name, target in group.items():
        if isinstance(name, str) and isinstance(target, str):
            out[name] = target
    return out


def discover_default_entry_name(connector_root: Path) -> tuple[str, str]:
    """Pick the single ``prow.connectors`` entry from ``pyproject.toml``.

    Returns ``(entry_name, target)`` where *target* is ``module:Class``.
    """

    pp = connector_root / "pyproject.toml"
    if not pp.is_file():
        raise ConnectorPackageError(
            f"No pyproject.toml in {connector_root}; cannot discover connector entry point.",
        )
    eps = parse_pyproject_connector_entry_points(pp)
    if not eps:
        raise ConnectorPackageError(
            "pyproject.toml has no [project.entry-points.'prow.connectors'] entries.",
        )
    if len(eps) > 1:
        raise ConnectorPackageError(
            "Multiple prow.connectors entry points found; dev mode requires exactly one.",
        )
    ((name, target),) = eps.items()
    return name, target


def entry_point_from_strings(entry_name: str, target: str) -> EntryPoint:
    """Build a :class:`EntryPoint` compatible with :mod:`importlib.metadata`."""

    _mod, _, attr = target.partition(":")
    if not attr:
        raise ConnectorPackageError(
            f"Invalid entry point target {target!r} (expected module:attr)."
        )
    return EntryPoint(name=entry_name, value=target, group="prow.connectors")


def config_defaults_from_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Extract ``default`` values from a JSON Schema object's ``properties``."""

    out: dict[str, Any] = {}
    props = schema.get("properties")
    if not isinstance(props, dict):
        return out
    for key, sub in props.items():
        if isinstance(sub, dict) and "default" in sub:
            out[key] = sub["default"]
    return out


def validate_manifest_shape(manifest: dict[str, Any], *, path: Path | None = None) -> None:
    """Minimal structural validation for connector manifests (Pass D)."""

    loc = f" ({path})" if path else ""
    required = ("name", "type", "config_schema")
    missing = [k for k in required if k not in manifest]
    if missing:
        raise ConnectorPackageError(f"Manifest missing required keys {missing!r}{loc}.")
    cs = manifest.get("config_schema")
    if not isinstance(cs, dict):
        raise ConnectorPackageError(f"config_schema must be an object{loc}.")


def validate_config_against_schema(schema: dict[str, Any], config: dict[str, Any]) -> None:
    try:
        jsonschema.validate(instance=config, schema=schema)
    except JsonSchemaValidationError as exc:
        raise ConnectorPackageError(f"Config validation failed: {exc.message}") from exc


def ensure_connector_importable(connector_root: Path, entry_module: str) -> None:
    """Insert *connector_root* on ``sys.path`` so the connector package imports."""

    root = connector_root.resolve()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
