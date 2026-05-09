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

"""Minimal connector base class (Pass C1)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from prow.connector.protocol.messages import HealthStatus

if TYPE_CHECKING:
    from prow.connector.context import ConnectorContext


class ConnectorBase:
    """Minimal base class for Pass C1. Later passes specialise by connector type."""

    def __init__(self, ctx: ConnectorContext) -> None:
        self.ctx = ctx

    async def setup(self) -> None:
        """Called once after construction, before the protocol loop waits."""

    async def teardown(self) -> None:
        """Called once after shutdown has been observed."""

    async def health(self) -> HealthStatus:
        """Return connector self-health for runtime probes."""

        return HealthStatus.HEALTHY
