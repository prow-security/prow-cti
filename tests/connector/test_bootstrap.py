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

from unittest.mock import MagicMock

from prow.api.connector_startup import build_supervisor_and_scheduler
from prow.config.loader import _builtin_defaults


def test_bootstrap_skips_missing_entry_points() -> None:
    config = _builtin_defaults()
    session_factory = MagicMock()
    supervisor, scheduler = build_supervisor_and_scheduler(config, session_factory, "0.0.0")
    registered = {inst.entry_point_name for inst in supervisor.list_instances()}
    assert registered == {
        "cisa-kev",
        "mitre-attack",
        "urlhaus",
        "threatfox",
        "malwarebazaar",
    }
    assert len(scheduler._schedules) == 5
