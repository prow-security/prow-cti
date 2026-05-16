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

from pathlib import Path

import pytest

from prow.config import load_config
from prow.config.loader import _builtin_defaults

_MINIMAL_YAML = """
database:
  url: postgresql+asyncpg://local/test
api:
  port: 9000
"""


def test_load_config_minimal_yaml(tmp_path: Path) -> None:
    path = tmp_path / "prow.yml"
    path.write_text(_MINIMAL_YAML, encoding="utf-8")
    cfg = load_config(path)
    assert cfg.database.url == "postgresql+asyncpg://local/test"
    assert cfg.api.port == 9000
    assert cfg.connectors == []


def test_load_config_invalid_yaml_raises(tmp_path: Path) -> None:
    path = tmp_path / "prow.yml"
    path.write_text("connectors:\n  - name: [unclosed", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid YAML"):
        load_config(path)


def test_load_config_missing_connectors_key(tmp_path: Path) -> None:
    path = tmp_path / "prow.yml"
    path.write_text("log:\n  level: debug\n", encoding="utf-8")
    cfg = load_config(path)
    assert cfg.connectors == []
    assert cfg.log.level == "debug"


def test_load_config_database_url_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "prow.yml"
    path.write_text(
        "database:\n  url: postgresql+asyncpg://from/yaml/db\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PROW_DATABASE_URL", "postgresql+asyncpg://from/env/db")
    cfg = load_config(path)
    assert cfg.database.url == "postgresql+asyncpg://from/env/db"


def test_load_config_api_port_env_override_as_int(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "prow.yml"
    path.write_text("api:\n  port: 8000\n", encoding="utf-8")
    monkeypatch.setenv("PROW_API_PORT", "3001")
    cfg = load_config(path)
    assert cfg.api.port == 3001
    assert isinstance(cfg.api.port, int)


def test_load_config_none_uses_builtin_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PROW_CONFIG_FILE", raising=False)
    expected = _builtin_defaults()
    cfg = load_config(None)
    assert len(cfg.connectors) == len(expected.connectors)
    assert [c.name for c in cfg.connectors] == [c.name for c in expected.connectors]


def test_builtin_defaults_abuse_ch_disabled() -> None:
    cfg = _builtin_defaults()
    by_name = {c.name: c for c in cfg.connectors}
    assert by_name["urlhaus"].enabled is False
    assert by_name["threatfox"].enabled is False
    assert by_name["malwarebazaar"].enabled is False
    assert by_name["cisa-kev"].enabled is True
    assert by_name["mitre-attack"].enabled is True


def test_load_config_prow_yml_example(repo_root: Path) -> None:
    example = repo_root / "prow.yml.example"
    cfg = load_config(example)
    assert len(cfg.connectors) == 5
    ids = [c.id for c in cfg.connectors]
    assert ids == [
        "cisa-kev",
        "mitre-attack",
        "urlhaus",
        "threatfox",
        "malwarebazaar",
    ]


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]
