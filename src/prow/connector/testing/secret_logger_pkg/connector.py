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
# WITHOUT WARRANTIES OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Logs secret-shaped fields for redaction integration tests."""

from __future__ import annotations

from prow.connector.base import ConnectorBase
from prow.connector.protocol.messages import LogLevel


class SecretLoggerConnector(ConnectorBase):
    async def setup(self) -> None:
        await self.ctx._transport.log(
            LogLevel.INFO,
            "secret.probe",
            fields={
                "api_key": self.ctx.config["api_key"],
                "nested": {"token": "tok-secret"},
                "auth.token": "literal-not-nested",
            },
            exception=None,
        )
