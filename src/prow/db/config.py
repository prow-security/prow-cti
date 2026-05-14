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

"""Database connection settings (pydantic-settings)."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Minimal async Postgres settings for `prow.db` (no engine singleton here)."""

    model_config = SettingsConfigDict(
        env_prefix="PROW_",
        env_file=".env",
        extra="ignore",
    )

    database_url: str = Field(
        default="postgresql+asyncpg://prow:prow@127.0.0.1:5432/prow",
        description="Async SQLAlchemy DSN (asyncpg driver).",
    )
    database_pool_size: int = Field(default=10, ge=1, le=100)
    database_pool_max_overflow: int = Field(default=5, ge=0, le=100)
    database_pool_timeout_seconds: float = Field(default=30.0, ge=1.0, le=300.0)


def load_database_settings() -> DatabaseSettings:
    """Load settings from the environment (new object each call for tests)."""

    return DatabaseSettings()
