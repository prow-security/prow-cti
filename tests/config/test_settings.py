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

from prow.config import Settings, clear_settings_cache, get_settings


def test_settings_database_url_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROW_DATABASE_URL", "postgresql+asyncpg://x:y@db:5432/app")
    clear_settings_cache()
    try:
        s = Settings()
        assert s.database_url == "postgresql+asyncpg://x:y@db:5432/app"
        assert get_settings().database_url == s.database_url
    finally:
        monkeypatch.delenv("PROW_DATABASE_URL", raising=False)
        clear_settings_cache()
