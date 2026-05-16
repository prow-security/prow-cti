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

import re
from pathlib import Path

import pytest

from prow.config import load_config

_ISO_DURATION = re.compile(r"^\d+[smhd]$")


@pytest.fixture
def prow_yml_example(repo_root: Path) -> Path:
    path = repo_root / "prow.yml.example"
    assert path.is_file(), "prow.yml.example must exist at repository root"
    return path


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_prow_yml_example_parses(prow_yml_example: Path) -> None:
    cfg = load_config(prow_yml_example)
    assert len(cfg.connectors) == 5


def test_prow_yml_example_explicit_ids(prow_yml_example: Path) -> None:
    cfg = load_config(prow_yml_example)
    for connector in cfg.connectors:
        assert connector.id is not None
        assert connector.id.strip() != ""


def test_prow_yml_example_unique_ids(prow_yml_example: Path) -> None:
    cfg = load_config(prow_yml_example)
    ids = [c.id for c in cfg.connectors]
    assert len(ids) == len(set(ids))


def test_prow_yml_example_schedule_durations(prow_yml_example: Path) -> None:
    cfg = load_config(prow_yml_example)
    for connector in cfg.connectors:
        assert _ISO_DURATION.match(connector.schedule), (
            f"{connector.name} schedule {connector.schedule!r} is not a valid ISO duration"
        )


def test_prow_yml_example_abuse_ch_disabled(prow_yml_example: Path) -> None:
    cfg = load_config(prow_yml_example)
    by_name = {c.name: c for c in cfg.connectors}
    assert by_name["urlhaus"].enabled is False
    assert by_name["threatfox"].enabled is False
    assert by_name["malwarebazaar"].enabled is False


def test_prow_yml_example_abuse_ch_auth_keys(prow_yml_example: Path) -> None:
    cfg = load_config(prow_yml_example)
    by_name = {c.name: c for c in cfg.connectors}
    for name in ("urlhaus", "threatfox", "malwarebazaar"):
        assert "auth_key" in by_name[name].config


def test_prow_yml_example_mitre_attack_allow_custom_types(prow_yml_example: Path) -> None:
    cfg = load_config(prow_yml_example)
    by_name = {c.name: c for c in cfg.connectors}
    assert by_name["mitre-attack"].allow_custom_types is True
