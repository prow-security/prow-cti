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

from __future__ import annotations

import pytest
from pydantic import ValidationError

from prow.config.loader import _builtin_defaults
from prow.config.schema import (
    ApiConfig,
    ConnectorInstanceConfig,
    DatabaseConfig,
    LogConfig,
    ProwConfig,
)


def test_prow_config_default_empty_connectors() -> None:
    cfg = ProwConfig()
    assert cfg.connectors == []


def test_builtin_defaults_has_five_connectors() -> None:
    cfg = _builtin_defaults()
    assert len(cfg.connectors) == 5
    names = {c.name for c in cfg.connectors}
    assert names == {
        "cisa-kev",
        "mitre-attack",
        "urlhaus",
        "threatfox",
        "malwarebazaar",
    }


def test_builtin_defaults_schedules() -> None:
    cfg = _builtin_defaults()
    by_name = {c.name: c for c in cfg.connectors}
    assert by_name["cisa-kev"].schedule == "6h"
    assert by_name["mitre-attack"].schedule == "24h"
    assert by_name["urlhaus"].schedule == "1h"
    assert by_name["threatfox"].schedule == "1h"
    assert by_name["malwarebazaar"].schedule == "6h"


def test_builtin_defaults_enabled_flags() -> None:
    cfg = _builtin_defaults()
    by_name = {c.name: c for c in cfg.connectors}
    assert by_name["cisa-kev"].enabled is True
    assert by_name["mitre-attack"].enabled is True
    assert by_name["urlhaus"].enabled is False
    assert by_name["threatfox"].enabled is False
    assert by_name["malwarebazaar"].enabled is False


def test_builtin_defaults_mitre_attack_allows_custom_types() -> None:
    cfg = _builtin_defaults()
    by_name = {c.name: c for c in cfg.connectors}
    assert by_name["mitre-attack"].allow_custom_types is True
    assert by_name["cisa-kev"].allow_custom_types is False


def test_connector_instance_derives_id_from_index() -> None:
    cfg = ProwConfig(
        connectors=[
            ConnectorInstanceConfig(name="urlhaus"),
            ConnectorInstanceConfig(name="urlhaus", enabled=False),
        ]
    )
    assert cfg.connectors[0].id == "urlhaus-0"
    assert cfg.connectors[1].id == "urlhaus-1"


def test_duplicate_resolved_ids_raise() -> None:
    with pytest.raises(ValueError, match="duplicate connector instance id"):
        ProwConfig(
            connectors=[
                ConnectorInstanceConfig(name="a", id="same"),
                ConnectorInstanceConfig(name="b", id="same"),
            ]
        )


def test_enabled_false_preserved() -> None:
    cfg = ProwConfig(connectors=[ConnectorInstanceConfig(name="cisa-kev", enabled=False)])
    assert cfg.connectors[0].enabled is False


def test_unknown_top_level_field_rejected() -> None:
    with pytest.raises(ValidationError):
        ProwConfig(unknown=True)  # type: ignore[call-arg]


def test_nested_config_defaults() -> None:
    assert DatabaseConfig().url == "postgresql+asyncpg://prow:prow@localhost:5432/prow"
    assert DatabaseConfig().pool_size == 10
    assert ApiConfig().host == "0.0.0.0"  # noqa: S104
    assert ApiConfig().port == 8000
    assert ApiConfig().cors_origins == ["*"]
    assert LogConfig().level == "info"
