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

"""Unit coverage for prow.stix.helpers — connector-facing factories."""

from __future__ import annotations

import json

import pytest

from prow.stix import (
    Bundle,
    DomainName,
    EmailAddr,
    File,
    Indicator,
    Ipv4Addr,
    Ipv6Addr,
    Malware,
    Relationship,
    Url,
    bundle,
    domain_observable,
    email_addr_observable,
    file_observable,
    indicator,
    ipv4_observable,
    ipv6_observable,
    malware,
    malware_id,
    relationship,
    url_observable,
    validate_stix_object,
)
from prow.stix._stix2_adapter import compute_sco_id

# ---------------------------------------------------------------------------
# SDO / SRO helpers.
# ---------------------------------------------------------------------------


def test_indicator_helper_produces_validatable_stix() -> None:
    ind = indicator(
        name="Bad URL",
        pattern="[url:value = 'http://evil.example/x']",
    )
    assert isinstance(ind, Indicator)
    assert ind.spec_version == "2.1"
    assert ind.type == "indicator"
    assert ind.id.startswith("indicator--")

    raw = json.loads(ind.model_dump_json())
    validate_stix_object(raw)


def test_indicator_helper_passes_optional_fields_through() -> None:
    ind = indicator(
        name="C2 IP",
        pattern="[ipv4-addr:value = '1.2.3.4']",
        indicator_types=["malicious-activity"],
        confidence=80,
        description="Observed in a phishing campaign",
        object_marking_refs=["marking-definition--94868c89-83c2-464b-929b-a1a8aa3c8487"],
    )
    raw = json.loads(ind.model_dump_json())
    assert raw["confidence"] == 80
    assert raw["description"] == "Observed in a phishing campaign"
    assert raw["indicator_types"] == ["malicious-activity"]
    assert raw["object_marking_refs"] == [
        "marking-definition--94868c89-83c2-464b-929b-a1a8aa3c8487"
    ]


def test_relationship_helper_accepts_objects_and_string_ids() -> None:
    obs = url_observable(value="http://evil.example/x")
    ind = indicator(name="Bad URL", pattern="[url:value = 'http://evil.example/x']")

    rel_objs = relationship(ind, "based-on", obs)
    rel_strs = relationship(ind.id, "based-on", obs.id)

    assert isinstance(rel_objs, Relationship)
    assert rel_objs.source_ref == ind.id
    assert rel_objs.target_ref == obs.id

    assert rel_strs.source_ref == ind.id
    assert rel_strs.target_ref == obs.id


def test_relationship_helper_rejects_unrecognised_types() -> None:
    with pytest.raises(TypeError):
        relationship(123, "based-on", "url--00000000-0000-4000-8000-000000000001")  # type: ignore[arg-type]


def test_bundle_helper_wraps_objects_and_validates() -> None:
    obs = url_observable(value="http://evil.example/x")
    ind = indicator(name="Bad URL", pattern="[url:value = 'http://evil.example/x']")
    rel = relationship(ind, "based-on", obs)
    b = bundle([obs, ind, rel])

    assert isinstance(b, Bundle)
    assert b.id.startswith("bundle--")
    assert len(b.objects) == 3

    raw = json.loads(b.model_dump_json())
    validate_stix_object(raw)


def test_bundle_helper_accepts_explicit_id() -> None:
    custom = "bundle--00000000-0000-4000-8000-000000000abc"
    b = bundle([url_observable(value="http://x")], id=custom)
    assert b.id == custom


# ---------------------------------------------------------------------------
# SCO helpers — deterministic ID matches adapter computation.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("helper", "stix_type", "value", "cls"),
    [
        (url_observable, "url", "https://evil.example/x", Url),
        (ipv4_observable, "ipv4-addr", "192.0.2.1", Ipv4Addr),
        (ipv6_observable, "ipv6-addr", "2001:db8::1", Ipv6Addr),
        (domain_observable, "domain-name", "evil.example", DomainName),
        (email_addr_observable, "email-addr", "alice@example.com", EmailAddr),
    ],
)
def test_simple_sco_helper_id_matches_adapter(
    helper: object, stix_type: str, value: str, cls: type
) -> None:
    obj = helper(value=value)  # type: ignore[operator]
    assert isinstance(obj, cls)
    assert obj.id == compute_sco_id(stix_type, {"value": value})


def test_simple_sco_helper_is_idempotent_for_same_value() -> None:
    a = url_observable(value="http://repeat.example")
    b = url_observable(value="http://repeat.example")
    assert a.id == b.id


def test_file_helper_picks_highest_precedence_hash_for_id() -> None:
    sha256 = "f" * 64
    md5 = "1" * 32
    f = file_observable(name="evil.exe", hashes={"SHA-256": sha256, "MD5": md5})
    assert isinstance(f, File)
    expected = compute_sco_id("file", {"hashes": {"SHA-256": sha256}, "name": "evil.exe"})
    assert f.id == expected
    # The full hashes dict still rides on the object even though only one
    # contributed to the ID.
    assert f.hashes == {"SHA-256": sha256, "MD5": md5}


def test_file_helper_falls_back_to_name_only_id() -> None:
    f = file_observable(name="evil.exe")
    expected = compute_sco_id("file", {"name": "evil.exe"})
    assert f.id == expected


def test_file_helper_requires_name_or_hashes() -> None:
    with pytest.raises(ValueError):
        file_observable()


def test_file_observable_with_extensions_produces_distinct_id() -> None:
    """File SCOs with different extensions must have different IDs."""
    base = file_observable(name="test.exe", hashes={"SHA-256": "a" * 64})
    with_ext = file_observable(
        name="test.exe",
        hashes={"SHA-256": "a" * 64},
        extensions={
            "windows-pebinary-ext": {
                "pe_type": "exe",
                "machine_hex": "014c",
            }
        },
    )
    assert base.id != with_ext.id, (
        "File SCO IDs must differ when extensions differ — "
        "extensions are spec-required contributing properties."
    )


def test_malware_id_normalizes_name() -> None:
    assert malware_id("Cobalt Strike") == malware_id("cobalt strike")
    assert malware_id("Cobalt Strike") == malware_id("  Cobalt Strike  ")


def test_malware_id_differs_by_family() -> None:
    assert malware_id("Cobalt Strike") != malware_id("Emotet")


def test_malware_id_is_stable() -> None:
    first = malware_id("Cobalt Strike")
    second = malware_id("Cobalt Strike")
    assert first == second


def test_malware_helper_uses_deterministic_id() -> None:
    obj = malware("Cobalt Strike")
    assert isinstance(obj, Malware)
    assert obj.id == malware_id("cobalt strike")


def test_malware_helper_non_deterministic_id() -> None:
    a = malware("Cobalt Strike", deterministic_id=False)
    b = malware("Cobalt Strike", deterministic_id=False)
    assert a.id != b.id


def test_file_observable_extensions_round_trip() -> None:
    """Extensions on File SCOs survive serialisation."""
    f = file_observable(
        name="malware.dll",
        extensions={
            "archive-ext": {"contains_refs": ["file--00000000-0000-0000-0000-000000000000"]}
        },
    )
    serialised = f.model_dump(mode="json")
    assert "extensions" in serialised
    assert "archive-ext" in serialised["extensions"]
