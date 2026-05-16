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

"""Parse ISO 8601-style duration strings used in prow.yml schedules."""

from __future__ import annotations

import re
from datetime import timedelta

_DURATION_RE = re.compile(r"^(?P<value>\d+)(?P<unit>[smhd])$")


def parse_iso8601_duration(value: str) -> timedelta:
    """Parse a duration such as ``30m``, ``6h``, or ``7d``."""

    text = value.strip()
    match = _DURATION_RE.match(text)
    if match is None:
        msg = (
            f"invalid schedule duration {value!r}: "
            "expected a positive integer followed by s, m, h, or d"
        )
        raise ValueError(msg)

    amount = int(match.group("value"))
    if amount <= 0:
        msg = f"invalid schedule duration {value!r}: value must be positive"
        raise ValueError(msg)

    unit = match.group("unit")
    if unit == "s":
        return timedelta(seconds=amount)
    if unit == "m":
        return timedelta(minutes=amount)
    if unit == "h":
        return timedelta(hours=amount)
    return timedelta(days=amount)
