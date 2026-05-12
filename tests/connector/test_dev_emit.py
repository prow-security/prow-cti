# Copyright 2026 Prow Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

from __future__ import annotations

import io
import re
from typing import Any

import pytest

from prow.connector.dev_emit import DevEmitHandler

_INDICATOR_GOOD: dict[str, Any] = {
    "type": "indicator",
    "spec_version": "2.1",
    "id": "indicator--8e2e2d2b-17d4-4cbf-938f-98ee46b3cd3f",
    "created": "2024-01-01T12:00:00.000Z",
    "modified": "2024-01-01T12:00:00.000Z",
    "pattern": "[ipv4-addr:value = '198.51.100.7']",
    "pattern_type": "stix",
    "valid_from": "2024-01-01T12:00:00.000Z",
}


@pytest.mark.asyncio
async def test_emit_accepts_valid_bundle() -> None:
    buf = io.StringIO()
    h = DevEmitHandler(stream=buf)
    bundle = {
        "type": "bundle",
        "id": "bundle--11111111-1111-4111-8111-111111111111",
        "objects": [_INDICATOR_GOOD],
    }
    ack = await h("dev", bundle)
    assert ack.accepted == 1
    assert ack.validation_failures == []
    line = buf.getvalue()
    assert re.match(
        r"^\[\d{2}:\d{2}:\d{2}\] emit: 1 objects \(1 indicator; 0 failed\) bundle=", line
    )


@pytest.mark.asyncio
async def test_emit_reports_invalid_object() -> None:
    buf = io.StringIO()
    h = DevEmitHandler(stream=buf)
    bad = dict(_INDICATOR_GOOD)
    del bad["pattern"]
    bundle = {
        "type": "bundle",
        "id": "bundle--22222222-2222-4222-8222-222222222222",
        "objects": [bad],
    }
    ack = await h("dev", bundle)
    assert ack.accepted == 0
    assert len(ack.validation_failures) == 1
