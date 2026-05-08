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

"""Test-only helpers — not part of the prow public API.

Lives under ``tests/`` so it cannot accidentally be imported by
runtime code. Holds:

* The mapping from STIX ``type`` to the corresponding prow Pydantic
  class. Mirrors the v0.1 modelled set in
  :mod:`prow.stix.types`. Keep in sync when new types are added.
* :func:`stix_equivalent` — a STIX-aware comparison that ignores
  irrelevant differences (timestamp precision normalisation, key
  ordering, dropped-empty-collection vs absent-field).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from prow.stix.types import (
    AttackPattern,
    Bundle,
    Campaign,
    DomainName,
    EmailAddr,
    File,
    Identity,
    Indicator,
    IntrusionSet,
    Ipv4Addr,
    Ipv6Addr,
    Malware,
    MarkingDefinition,
    ObservedData,
    Relationship,
    Report,
    Sighting,
    Software,
    ThreatActor,
    Tool,
    Url,
    Vulnerability,
    _StixCommon,
)

MODELLED_TYPES: dict[str, type[_StixCommon]] = {
    "attack-pattern": AttackPattern,
    "bundle": Bundle,
    "campaign": Campaign,
    "domain-name": DomainName,
    "email-addr": EmailAddr,
    "file": File,
    "identity": Identity,
    "indicator": Indicator,
    "intrusion-set": IntrusionSet,
    "ipv4-addr": Ipv4Addr,
    "ipv6-addr": Ipv6Addr,
    "malware": Malware,
    "marking-definition": MarkingDefinition,
    "observed-data": ObservedData,
    "relationship": Relationship,
    "report": Report,
    "sighting": Sighting,
    "software": Software,
    "threat-actor": ThreatActor,
    "tool": Tool,
    "url": Url,
    "vulnerability": Vulnerability,
}

_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")


def _normalise_timestamp(value: str) -> str:
    """Round any STIX-shaped timestamp string to millisecond precision UTC.

    Examples:

    * ``"2014-05-08T09:00:00.000000Z"`` → ``"2014-05-08T09:00:00.000Z"``
    * ``"2014-05-08T09:00:00Z"``        → ``"2014-05-08T09:00:00.000Z"``
    * ``"2014-05-08T09:00:00.123Z"``    → ``"2014-05-08T09:00:00.123Z"``
    """
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    parsed = parsed.astimezone(UTC)
    millis = parsed.microsecond // 1000
    return parsed.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def _normalise(value: Any) -> Any:
    """Recursively canonicalise a STIX object for equivalence comparison.

    * Timestamp strings collapse to millisecond precision UTC.
    * Empty lists / dicts / ``None`` are dropped (prow drops these on
      dump; some upstream examples omit them, others emit empties).
    * ``spec_version: "2.1"`` is dropped at the object level because
      the spec treats absent and ``"2.1"`` as equivalent for STIX
      2.1 objects (especially SCOs embedded inside bundles), and the
      OASIS examples are inconsistent about including it.
    * Custom ``x_*`` keys at the top level are flattened from the
      ``extensions`` dict to the top level so the comparison sees
      them in the same place regardless of where the producer wrote
      them.
    """
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, val in value.items():
            normalised = _normalise(val)
            if normalised is None or normalised == [] or normalised == {}:
                continue
            out[key] = normalised
        if out.get("spec_version") == "2.1":
            out.pop("spec_version")
        if "extensions" in out and isinstance(out["extensions"], dict):
            ext = dict(out["extensions"])
            for ext_key in list(ext.keys()):
                if isinstance(ext_key, str) and ext_key.startswith("x_"):
                    out[ext_key] = ext.pop(ext_key)
            if ext:
                out["extensions"] = ext
            else:
                out.pop("extensions")
        return out
    if isinstance(value, list):
        return [_normalise(item) for item in value]
    if isinstance(value, str) and _TIMESTAMP_RE.match(value):
        return _normalise_timestamp(value)
    return value


def stix_equivalent(left: Any, right: Any) -> bool:
    """Compare two STIX-shaped Python values for spec-equivalent content.

    Returns ``True`` when the two values represent the same STIX
    object after normalising timestamp precision, dropping empty
    collections, and flattening custom-property location.
    """
    return _normalise(left) == _normalise(right)
