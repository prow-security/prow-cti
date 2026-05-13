# Copyright 2026 Prow Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

from __future__ import annotations

from prow.connector.base import ConnectorBase

_INDICATOR = {
    "type": "indicator",
    "spec_version": "2.1",
    "id": "indicator--8e2e2d2b-17d4-4cbf-938f-98ee46b3cd3f",
    "created": "2024-01-01T12:00:00.000Z",
    "modified": "2024-01-01T12:00:00.000Z",
    "pattern": "[ipv4-addr:value = '198.51.100.7']",
    "pattern_type": "stix",
    "valid_from": "2024-01-01T12:00:00.000Z",
}


class GoodConnector(ConnectorBase):
    async def setup(self) -> None:
        return

    async def fetch(self) -> None:
        bundle = {
            "type": "bundle",
            "id": "bundle--11111111-1111-4111-8111-111111111111",
            "objects": [_INDICATOR],
        }
        await self.ctx.emit(bundle)
