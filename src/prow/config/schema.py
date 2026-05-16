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

"""Pydantic models for prow.yml and built-in defaults."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator


class ConnectorInstanceConfig(BaseModel):
    """One connector instance in prow.yml."""

    name: str
    id: str | None = None
    enabled: bool = True
    schedule: str = "24h"
    config: dict[str, Any] = {}

    model_config = ConfigDict(extra="forbid")


class DatabaseConfig(BaseModel):
    url: str = "postgresql+asyncpg://prow:prow@localhost:5432/prow"
    pool_size: int = 10
    pool_max_overflow: int = 5
    pool_timeout_seconds: int = 30

    model_config = ConfigDict(extra="forbid")


class ApiConfig(BaseModel):
    host: str = "0.0.0.0"  # noqa: S104
    port: int = 8000
    cors_origins: list[str] = ["*"]

    model_config = ConfigDict(extra="forbid")


class LogConfig(BaseModel):
    level: str = "info"

    model_config = ConfigDict(extra="forbid")


class ProwConfig(BaseModel):
    connectors: list[ConnectorInstanceConfig] = []
    database: DatabaseConfig = DatabaseConfig()
    api: ApiConfig = ApiConfig()
    log: LogConfig = LogConfig()

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_unique_instance_ids(self) -> ProwConfig:
        """Resolve derived IDs and reject duplicates."""

        seen: dict[str, int] = {}
        for index, connector in enumerate(self.connectors):
            resolved_id = connector.id
            if resolved_id is None:
                resolved_id = f"{connector.name}-{index}"
                object.__setattr__(connector, "id", resolved_id)
            elif not resolved_id.strip():
                msg = f"connector at index {index} ({connector.name!r}) has empty id"
                raise ValueError(msg)

            if resolved_id in seen:
                msg = f"duplicate connector instance id: {resolved_id!r}"
                raise ValueError(msg)
            seen[resolved_id] = index

        return self
