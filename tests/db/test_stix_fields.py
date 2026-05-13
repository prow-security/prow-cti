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

from datetime import UTC, datetime

import pytest

from prow.db.stix_fields import (
    extract_stix_persistence_fields,
    parse_stix_datetime,
    relationship_triple_key,
)


def test_extract_sdo_identity_and_modified() -> None:
    obj = {
        "type": "indicator",
        "spec_version": "2.1",
        "id": "indicator--8e2e2d2b-17d4-4cbf-938f-98ee46b3cd3f",
        "created": "2024-01-01T12:00:00.000Z",
        "modified": "2024-01-02T12:00:00.000Z",
        "pattern": "[ipv4-addr:value = '198.51.100.7']",
        "pattern_type": "stix",
        "valid_from": "2024-01-01T12:00:00.000Z",
    }
    fields = extract_stix_persistence_fields(obj)
    assert fields.stix_id == "indicator--8e2e2d2b-17d4-4cbf-938f-98ee46b3cd3f"
    assert fields.stix_type == "indicator"
    assert fields.modified == datetime(2024, 1, 2, 12, 0, tzinfo=UTC)


def test_extract_sco_modified_is_none() -> None:
    obj = {
        "type": "ipv4-addr",
        "spec_version": "2.1",
        "id": "ipv4-addr--cd0f996f-f345-4528-9707-45cd63f36ddd",
        "value": "198.51.100.3",
    }
    fields = extract_stix_persistence_fields(obj)
    assert fields.stix_type == "ipv4-addr"
    assert fields.modified is None
    assert fields.created is None


def test_parse_stix_datetime_accepts_z_suffix() -> None:
    dt = parse_stix_datetime("2024-01-01T12:00:00.000Z", field_name="created")
    assert dt == datetime(2024, 1, 1, 12, 0, tzinfo=UTC)


def test_relationship_triple_key_helper() -> None:
    rel = {
        "type": "relationship",
        "source_ref": "indicator--a",
        "relationship_type": "indicates",
        "target_ref": "malware--b",
    }
    assert relationship_triple_key(rel) == ("indicator--a", "indicates", "malware--b")


def test_relationship_triple_key_non_relationship() -> None:
    assert relationship_triple_key({"type": "indicator", "id": "x"}) is None


def test_extract_requires_id_and_type() -> None:
    with pytest.raises(ValueError, match="id"):
        extract_stix_persistence_fields({"type": "indicator"})
    with pytest.raises(ValueError, match="type"):
        extract_stix_persistence_fields({"id": "indicator--x"})
