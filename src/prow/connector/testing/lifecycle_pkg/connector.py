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

"""Minimal connector used by Pass C1 lifecycle integration tests."""

from __future__ import annotations

from prow.connector.base import ConnectorBase
from prow.connector.protocol.messages import LogLevel
from prow.stix.helpers import bundle as mk_bundle
from prow.stix.helpers import indicator


class LifecycleConnector(ConnectorBase):
    """Emits one bundle, logs, touches state — then waits for shutdown."""

    async def setup(self) -> None:
        ind = indicator(
            name="lifecycle",
            pattern="[ipv4-addr:value = '192.0.2.1']",
            pattern_type="stix",
            confidence=50,
            indicator_types=["malicious-activity"],
        )
        bundle = mk_bundle([ind])
        await self.ctx.emit(bundle)
        await self.ctx._transport.log(
            LogLevel.INFO,
            "lifecycle-log",
            fields={"channel": "test"},
            exception=None,
        )
        await self.ctx.set_state("cursor", "done")
        await self.ctx.get_state("cursor")
