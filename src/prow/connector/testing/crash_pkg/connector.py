# Copyright 2026 Prow Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
#
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Connector that fails during setup after printing to stderr."""

from __future__ import annotations

from prow.connector.base import ConnectorBase
from prow.stix.helpers import bundle as mk_bundle
from prow.stix.helpers import indicator


class CrashConnector(ConnectorBase):
    async def setup(self) -> None:
        ind = indicator(
            name="crash",
            pattern="[ipv4-addr:value = '192.0.2.2']",
            pattern_type="stix",
            confidence=50,
            indicator_types=["malicious-activity"],
        )
        bundle = mk_bundle([ind])
        await self.ctx.emit(bundle)
        raise RuntimeError("crash_connector_on_purpose")
