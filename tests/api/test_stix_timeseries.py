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

"""Unit tests for STIX list sorting and ingest timeseries (mocked session)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

import prow.db.repositories as repos
from prow.db.repositories import SqlAlchemyStixObjectRepository


class _FrozenDateTime:
    """Deterministic ``datetime`` facade for :meth:`get_ingest_timeseries`."""

    UTC = UTC
    min = datetime.min

    @staticmethod
    def now(tz=None):
        return datetime(2026, 5, 14, 12, 0, 0, tzinfo=tz or UTC)

    @staticmethod
    def combine(d, t, tzinfo=None):
        return datetime.combine(d, t, tzinfo=tzinfo)


@pytest.fixture
def frozen_datetime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repos, "datetime", _FrozenDateTime)


@pytest.mark.asyncio
async def test_get_ingest_timeseries_merges_counts_and_fills_days(
    frozen_datetime: None,
) -> None:
    session = AsyncMock()
    exec_result = MagicMock()
    exec_result.all.return_value = [
        (date(2026, 5, 12), "indicator", 5),
        (date(2026, 5, 12), "vulnerability", 2),
        (date(2026, 5, 14), "indicator", 1591),
        (date(2026, 5, 14), "vulnerability", 10),
    ]
    session.execute = AsyncMock(return_value=exec_result)

    repo = SqlAlchemyStixObjectRepository(session)
    out = await repo.get_ingest_timeseries(days=3)

    assert out["days"] == 3
    assert len(out["series"]) == 3
    assert out["series"][0] == {"date": "2026-05-12", "indicator": 5, "vulnerability": 2}
    assert out["series"][1] == {"date": "2026-05-13", "indicator": 0, "vulnerability": 0}
    assert out["series"][2] == {"date": "2026-05-14", "indicator": 1591, "vulnerability": 10}


@pytest.mark.asyncio
async def test_list_objects_supported_sort_modes() -> None:
    """Smoke that list_objects runs for each supported sort mode (session fully mocked)."""

    class _ScalarResult:
        def all(self):
            return []

    session = AsyncMock()
    session.scalar = AsyncMock(return_value=0)
    session.scalars = AsyncMock(return_value=_ScalarResult())

    repo = SqlAlchemyStixObjectRepository(session)

    for sort in ("ingested_at_desc", "created_desc", "confidence_desc"):
        await repo.list_objects(stix_type="indicator", limit=3, offset=0, sort=sort)

    assert session.scalars.await_count == 3
