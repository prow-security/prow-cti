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

from datetime import timedelta

import pytest

from prow.connector.duration import parse_iso8601_duration


def test_parse_minutes_hours_days() -> None:
    assert parse_iso8601_duration("30m") == timedelta(minutes=30)
    assert parse_iso8601_duration("6h") == timedelta(hours=6)
    assert parse_iso8601_duration("7d") == timedelta(days=7)


def test_parse_invalid_raises() -> None:
    with pytest.raises(ValueError, match="invalid schedule duration"):
        parse_iso8601_duration("not-a-duration")
