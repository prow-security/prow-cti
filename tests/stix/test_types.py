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

"""Unit coverage for prow.stix.types — Pydantic v2 boundary models."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from prow.stix.types import (
    Bundle,
    DomainName,
    EmailAddr,
    File,
    Identity,
    Indicator,
    Ipv4Addr,
    Ipv6Addr,
    MarkingDefinition,
    Relationship,
    Url,
    Vulnerability,
)

# ---------------------------------------------------------------------------
# Datetime serialisation — the failure mode the design note calls out.
# ---------------------------------------------------------------------------


def test_indicator_timestamp_serialises_with_millisecond_precision() -> None:
    raw = {
        "type": "indicator",
        "spec_version": "2.1",
        "id": "indicator--00000000-0000-4000-8000-000000000001",
        "created": "2024-01-01T12:00:00.123Z",
        "modified": "2024-01-01T12:00:00.123Z",
        "pattern": "[ipv4-addr:value = '1.2.3.4']",
        "pattern_type": "stix",
        "valid_from": "2024-01-01T12:00:00.123Z",
    }
    ind = Indicator.model_validate(raw)
    out = ind.model_dump(mode="json")
    assert out["created"] == "2024-01-01T12:00:00.123Z"
    assert out["modified"] == "2024-01-01T12:00:00.123Z"
    assert out["valid_from"] == "2024-01-01T12:00:00.123Z"


def test_naive_datetime_is_treated_as_utc_on_serialise() -> None:
    naive = datetime(2024, 1, 1, 12, 0, 0)
    aware = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    ind_naive = Indicator(
        id="indicator--00000000-0000-4000-8000-000000000001",
        created=naive,
        modified=naive,
        pattern="[ipv4-addr:value = '1.2.3.4']",
        pattern_type="stix",
        valid_from=naive,
    )
    ind_aware = Indicator(
        id="indicator--00000000-0000-4000-8000-000000000001",
        created=aware,
        modified=aware,
        pattern="[ipv4-addr:value = '1.2.3.4']",
        pattern_type="stix",
        valid_from=aware,
    )
    assert ind_naive.model_dump(mode="json")["created"] == "2024-01-01T12:00:00.000Z"
    assert ind_aware.model_dump(mode="json")["created"] == "2024-01-01T12:00:00.000Z"


# ---------------------------------------------------------------------------
# Construction with minimal required fields.
# ---------------------------------------------------------------------------


def _ts() -> datetime:
    return datetime(2024, 1, 1, tzinfo=UTC)


def test_indicator_minimal_construction() -> None:
    ind = Indicator(
        id="indicator--00000000-0000-4000-8000-000000000001",
        created=_ts(),
        modified=_ts(),
        pattern="[ipv4-addr:value = '1.2.3.4']",
        pattern_type="stix",
        valid_from=_ts(),
    )
    assert ind.type == "indicator"
    assert ind.spec_version == "2.1"


def test_indicator_missing_required_field_raises() -> None:
    with pytest.raises(ValidationError):
        Indicator(  # type: ignore[call-arg]
            id="indicator--00000000-0000-4000-8000-000000000001",
            created=_ts(),
            modified=_ts(),
            pattern_type="stix",
            valid_from=_ts(),
        )


def test_indicator_wrong_field_type_raises() -> None:
    with pytest.raises(ValidationError):
        Indicator(
            id="indicator--00000000-0000-4000-8000-000000000001",
            created=_ts(),
            modified=_ts(),
            pattern="[ipv4-addr:value = '1.2.3.4']",
            pattern_type="stix",
            valid_from=_ts(),
            confidence=200,  # out of range 0..100
        )


def test_vulnerability_minimal() -> None:
    v = Vulnerability(
        id="vulnerability--00000000-0000-4000-8000-000000000001",
        created=_ts(),
        modified=_ts(),
        name="CVE-2024-12345",
    )
    out = v.model_dump(mode="json")
    assert out["type"] == "vulnerability"
    assert out["name"] == "CVE-2024-12345"


def test_relationship_minimal() -> None:
    rel = Relationship(
        id="relationship--00000000-0000-4000-8000-000000000001",
        created=_ts(),
        modified=_ts(),
        relationship_type="based-on",
        source_ref="indicator--00000000-0000-4000-8000-000000000002",
        target_ref="url--00000000-0000-4000-8000-000000000003",
    )
    assert rel.type == "relationship"


def test_marking_definition_minimal() -> None:
    md = MarkingDefinition(
        id="marking-definition--94868c89-83c2-464b-929b-a1a8aa3c8487",
        created=_ts(),
        name="TLP:CLEAR",
    )
    assert md.type == "marking-definition"


# ---------------------------------------------------------------------------
# SCO models.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cls", "stix_type", "value"),
    [
        (Ipv4Addr, "ipv4-addr", "192.0.2.1"),
        (Ipv6Addr, "ipv6-addr", "2001:db8::1"),
        (DomainName, "domain-name", "example.com"),
        (Url, "url", "https://example.com/x"),
        (EmailAddr, "email-addr", "alice@example.com"),
    ],
)
def test_simple_sco_constructs_and_dumps(cls: Any, stix_type: str, value: str) -> None:
    obj = cls(id=f"{stix_type}--00000000-0000-4000-8000-000000000001", value=value)
    out = obj.model_dump(mode="json")
    assert out["type"] == stix_type
    assert out["value"] == value
    # SCOs do not have created/modified
    assert "created" not in out
    assert "modified" not in out


def test_file_sco_with_hashes() -> None:
    f = File(
        id="file--00000000-0000-4000-8000-000000000001",
        name="evil.exe",
        size=1024,
        hashes={"SHA-256": "a" * 64},
    )
    out = f.model_dump(mode="json")
    assert out["type"] == "file"
    assert out["name"] == "evil.exe"
    assert out["hashes"] == {"SHA-256": "a" * 64}


# ---------------------------------------------------------------------------
# Custom STIX extensions: round-trip via the extensions dict.
# ---------------------------------------------------------------------------


def test_custom_x_property_lifts_to_extensions_then_flattens_back() -> None:
    raw = {
        "type": "indicator",
        "spec_version": "2.1",
        "id": "indicator--00000000-0000-4000-8000-000000000001",
        "created": "2024-01-01T00:00:00.000Z",
        "modified": "2024-01-01T00:00:00.000Z",
        "pattern": "[ipv4-addr:value = '1.2.3.4']",
        "pattern_type": "stix",
        "valid_from": "2024-01-01T00:00:00.000Z",
        "x_acme_threat_score": 95,
        "x_acme_tags": ["c2", "phishing"],
    }
    ind = Indicator.model_validate(raw)
    assert ind.extensions["x_acme_threat_score"] == 95
    assert ind.extensions["x_acme_tags"] == ["c2", "phishing"]

    out = ind.model_dump(mode="json")
    assert out["x_acme_threat_score"] == 95
    assert out["x_acme_tags"] == ["c2", "phishing"]
    assert "extensions" not in out


def test_extension_definition_extensions_stay_nested() -> None:
    ext_def_id = "extension-definition--abc12345-1234-5678-9abc-def012345678"
    raw = {
        "type": "indicator",
        "spec_version": "2.1",
        "id": "indicator--00000000-0000-4000-8000-000000000001",
        "created": "2024-01-01T00:00:00.000Z",
        "modified": "2024-01-01T00:00:00.000Z",
        "pattern": "[ipv4-addr:value = '1.2.3.4']",
        "pattern_type": "stix",
        "valid_from": "2024-01-01T00:00:00.000Z",
        "extensions": {ext_def_id: {"extension_type": "property-extension", "foo": "bar"}},
    }
    ind = Indicator.model_validate(raw)
    out = ind.model_dump(mode="json")
    assert out["extensions"] == {ext_def_id: {"extension_type": "property-extension", "foo": "bar"}}


def test_mixed_extensions_split_on_dump() -> None:
    ext_def_id = "extension-definition--abc12345-1234-5678-9abc-def012345678"
    raw = {
        "type": "indicator",
        "spec_version": "2.1",
        "id": "indicator--00000000-0000-4000-8000-000000000001",
        "created": "2024-01-01T00:00:00.000Z",
        "modified": "2024-01-01T00:00:00.000Z",
        "pattern": "[ipv4-addr:value = '1.2.3.4']",
        "pattern_type": "stix",
        "valid_from": "2024-01-01T00:00:00.000Z",
        "x_custom_field": "value",
        "extensions": {ext_def_id: {"extension_type": "property-extension"}},
    }
    out = Indicator.model_validate(raw).model_dump(mode="json")
    assert out["x_custom_field"] == "value"
    assert out["extensions"] == {ext_def_id: {"extension_type": "property-extension"}}


# ---------------------------------------------------------------------------
# Bundle: discriminated union dispatch and round-trip.
# ---------------------------------------------------------------------------


def test_bundle_dispatches_via_type_discriminator() -> None:
    raw = {
        "type": "bundle",
        "id": "bundle--00000000-0000-4000-8000-000000000001",
        "objects": [
            {
                "type": "url",
                "spec_version": "2.1",
                "id": "url--00000000-0000-4000-8000-000000000002",
                "value": "https://evil.example/p",
            },
            {
                "type": "ipv4-addr",
                "spec_version": "2.1",
                "id": "ipv4-addr--00000000-0000-4000-8000-000000000003",
                "value": "192.0.2.1",
            },
        ],
    }
    bundle = Bundle.model_validate(raw)
    assert isinstance(bundle.objects[0], Url)
    assert isinstance(bundle.objects[1], Ipv4Addr)


def test_bundle_full_external_round_trip() -> None:
    raw = {
        "type": "bundle",
        "id": "bundle--00000000-0000-4000-8000-000000000001",
        "objects": [
            {
                "type": "indicator",
                "spec_version": "2.1",
                "id": "indicator--00000000-0000-4000-8000-000000000002",
                "created": "2024-01-01T00:00:00.000Z",
                "modified": "2024-01-01T00:00:00.000Z",
                "pattern": "[ipv4-addr:value = '1.2.3.4']",
                "pattern_type": "stix",
                "valid_from": "2024-01-01T00:00:00.000Z",
            }
        ],
    }
    bundle = Bundle.parse_external(raw)
    out = json.loads(bundle.model_dump_json())
    assert out["type"] == "bundle"
    assert out["objects"][0]["pattern"] == "[ipv4-addr:value = '1.2.3.4']"


# ---------------------------------------------------------------------------
# Identity / Report shape sanity (representative SDOs with required fields
# beyond the SDO base class).
# ---------------------------------------------------------------------------


def test_identity_requires_name() -> None:
    with pytest.raises(ValidationError):
        Identity(  # type: ignore[call-arg]
            id="identity--00000000-0000-4000-8000-000000000001",
            created=_ts(),
            modified=_ts(),
        )


# ---------------------------------------------------------------------------
# Performance budget — design note's 10k-indicator / 5-second commitment.
# ---------------------------------------------------------------------------


def test_indicator_validation_performance_budget() -> None:
    """Validate + construct 10,000 indicators in well under the budget.

    The design note pins **5 seconds** on one CPU core for 10k
    indicators. CI runners are slower than developer laptops so we
    leave headroom — the assertion ceiling is **10 seconds** to
    keep CI green on a tired machine while still catching regressions
    that move us materially closer to the budget. The real budget
    measurement happens locally before merge.
    """
    raw = {
        "type": "indicator",
        "spec_version": "2.1",
        "id": "indicator--00000000-0000-4000-8000-000000000001",
        "created": "2024-01-01T12:00:00.000Z",
        "modified": "2024-01-01T12:00:00.000Z",
        "pattern": "[ipv4-addr:value = '1.2.3.4']",
        "pattern_type": "stix",
        "valid_from": "2024-01-01T12:00:00.000Z",
    }
    start = time.perf_counter()
    for _ in range(10_000):
        Indicator.parse_external(raw)
    elapsed = time.perf_counter() - start
    assert elapsed < 10.0, (
        f"Performance budget breach: {elapsed:.2f}s for 10,000 indicators. "
        "Design note pins 5s as the goal; this test allows 10s for CI variance. "
        "Consider switching to fastjsonschema (pre-authorised by the design note)."
    )
