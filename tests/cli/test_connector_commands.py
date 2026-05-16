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

from unittest.mock import AsyncMock, MagicMock, patch

from typer.testing import CliRunner

from prow.cli.connector import app
from prow.config.schema import ConnectorInstanceConfig, ProwConfig

runner = CliRunner()


def _sample_config() -> ProwConfig:
    return ProwConfig(
        connectors=[
            ConnectorInstanceConfig(
                name="cisa-kev",
                id="cisa-kev",
                enabled=True,
                schedule="6h",
            ),
            ConnectorInstanceConfig(
                name="mitre-attack",
                id="mitre-attack",
                enabled=False,
                schedule="24h",
            ),
        ],
    )


def test_connector_list_renders_table() -> None:
    config = _sample_config()

    with (
        patch("prow.cli.connector.load_cli_config", return_value=config),
        patch("prow.cli.connector.load_database_settings"),
        patch("prow.cli.connector.create_async_engine_from_settings") as mock_engine,
        patch("prow.cli.connector.check_database", new_callable=AsyncMock, return_value=True),
        patch("prow.cli.connector.create_async_sessionmaker"),
        patch("prow.cli.connector.build_list_rows", new_callable=AsyncMock) as mock_rows,
        patch("prow.cli.connector.dispose_engine", new_callable=AsyncMock),
    ):
        mock_rows.return_value = [
            ("cisa-kev", "cisa-kev", "config-only", "10", "1m ago"),
            ("mitre-attack", "mitre-attack", "disabled", "—", "never"),
        ]
        mock_engine.return_value = MagicMock()
        result = runner.invoke(app, ["list"])

    assert result.exit_code == 0
    assert "NAME" in result.stdout
    assert "cisa-kev" in result.stdout
    assert "OBJECTS" in result.stdout


def test_connector_purge_requires_confirmation() -> None:
    config = _sample_config()

    with (
        patch("prow.cli.connector.load_cli_config", return_value=config),
        patch("prow.cli.connector.load_database_settings"),
        patch("prow.cli.connector.create_async_engine_from_settings") as mock_engine,
        patch("prow.cli.connector.check_database", new_callable=AsyncMock, return_value=True),
        patch("prow.cli.connector.create_async_sessionmaker"),
        patch("prow.cli.connector.count_before_purge", new_callable=AsyncMock, return_value=42),
        patch("prow.cli.connector.purge_connector_data", new_callable=AsyncMock) as mock_purge,
        patch("prow.cli.connector.dispose_engine", new_callable=AsyncMock),
    ):
        mock_engine.return_value = MagicMock()
        result = runner.invoke(app, ["purge", "cisa-kev"], input="wrong\n")

    assert result.exit_code == 1
    mock_purge.assert_not_called()


def test_connector_purge_yes_deletes() -> None:
    config = _sample_config()

    with (
        patch("prow.cli.connector.load_cli_config", return_value=config),
        patch("prow.cli.connector.load_database_settings"),
        patch("prow.cli.connector.create_async_engine_from_settings") as mock_engine,
        patch("prow.cli.connector.check_database", new_callable=AsyncMock, return_value=True),
        patch("prow.cli.connector.create_async_sessionmaker"),
        patch("prow.cli.connector.count_before_purge", new_callable=AsyncMock, return_value=42),
        patch(
            "prow.cli.connector.purge_connector_data", new_callable=AsyncMock, return_value=42
        ) as mock_purge,
        patch("prow.cli.connector.dispose_engine", new_callable=AsyncMock),
    ):
        mock_engine.return_value = MagicMock()
        result = runner.invoke(app, ["purge", "cisa-kev", "--yes"])

    assert result.exit_code == 0
    mock_purge.assert_awaited_once()
    assert mock_purge.await_args.args[1] == ["cisa-kev"]
    assert "42" in result.stdout


def test_resolve_instance_ids_from_config() -> None:
    from prow.cli.connector_ops import resolve_instance_ids

    config = _sample_config()
    assert resolve_instance_ids(config, "cisa-kev") == ["cisa-kev"]
