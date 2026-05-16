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

"""Load prow.yml, apply env overrides, and return validated :class:`ProwConfig`."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from yaml import YAMLError

from prow.config.schema import ConnectorInstanceConfig, ProwConfig

_ENV_OVERRIDES: dict[str, tuple[str, type]] = {
    "PROW_DATABASE_URL": ("database.url", str),
    "PROW_DATABASE_POOL_SIZE": ("database.pool_size", int),
    "PROW_API_HOST": ("api.host", str),
    "PROW_API_PORT": ("api.port", int),
    "PROW_LOG_LEVEL": ("log.level", str),
}

BUILTIN_CONNECTOR_DEFAULTS: list[dict[str, Any]] = [
    {"name": "cisa-kev", "id": "cisa-kev", "schedule": "6h", "enabled": True},
    {"name": "mitre-attack", "id": "mitre-attack", "schedule": "24h", "enabled": True},
    {"name": "urlhaus", "id": "urlhaus", "schedule": "1h", "enabled": True},
    {"name": "threatfox", "id": "threatfox", "schedule": "1h", "enabled": True},
    {"name": "malwarebazaar", "id": "malwarebazaar", "schedule": "6h", "enabled": True},
]

_CONFIG_CANDIDATES = (Path("prow.yml"), Path("/etc/prow/prow.yml"))


def load_config(path: Path | None = None) -> ProwConfig:
    """Load configuration from YAML with top-level env overrides."""

    if path is not None:
        config_path = path
    else:
        found = _find_config_file()
        if found is None:
            return _builtin_defaults()
        config_path = found

    if not config_path.is_file():
        msg = f"configuration file not found: {config_path}"
        raise FileNotFoundError(msg)

    try:
        raw = config_path.read_text(encoding="utf-8")
        parsed = yaml.safe_load(raw)
    except YAMLError as exc:
        msg = f"invalid YAML in {config_path}: {exc}"
        raise ValueError(msg) from exc

    if parsed is None:
        data: dict[str, Any] = {}
    elif not isinstance(parsed, dict):
        msg = f"configuration root must be a mapping, got {type(parsed).__name__}"
        raise ValueError(msg)
    else:
        data = parsed

    data = _apply_env_overrides(data)
    return ProwConfig(**data)


def _find_config_file() -> Path | None:
    env_path = os.environ.get("PROW_CONFIG_FILE")
    if env_path:
        candidate = Path(env_path)
        return candidate if candidate.is_file() else None

    for candidate in _CONFIG_CANDIDATES:
        if candidate.is_file():
            return candidate

    return None


def _apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    result = dict(data)
    for env_name, (dotted_path, cast) in _ENV_OVERRIDES.items():
        raw = os.environ.get(env_name)
        if raw is None:
            continue
        try:
            value: Any = cast(raw)
        except (TypeError, ValueError) as exc:
            msg = f"invalid value for {env_name}: {raw!r}"
            raise ValueError(msg) from exc
        _set_nested(result, dotted_path.split("."), value)
    return result


def _set_nested(data: dict[str, Any], keys: list[str], value: Any) -> None:
    current: dict[str, Any] = data
    for key in keys[:-1]:
        nested = current.get(key)
        if not isinstance(nested, dict):
            nested = {}
            current[key] = nested
        current = nested
    current[keys[-1]] = value


def _builtin_defaults() -> ProwConfig:
    """Zero-config defaults: all built-in connectors enabled."""

    connectors = [ConnectorInstanceConfig(**entry) for entry in BUILTIN_CONNECTOR_DEFAULTS]
    return ProwConfig(connectors=connectors)
