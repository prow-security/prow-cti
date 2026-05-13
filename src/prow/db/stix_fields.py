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

"""Extract canonical persistence columns from validated STIX object dicts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


def parse_stix_datetime(value: object, *, field_name: str) -> datetime | None:
    """Parse STIX timestamps (ISO-8601 strings ending in ``Z`` allowed)."""

    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    msg = f"{field_name} must be a datetime or ISO-8601 string, got {type(value).__name__}"
    raise TypeError(msg)


def relationship_triple_key(relationship: dict[str, Any]) -> tuple[str, str, str] | None:
    """Return ``(source_ref, relationship_type, target_ref)`` for query-level aggregation only.

    This does **not** define storage uniqueness. Multiple ``relationship`` SDOs may
    share the same triple while retaining distinct STIX ``id`` values (and separate
    ``stix_objects`` rows).
    """

    if relationship.get("type") != "relationship":
        return None
    src = relationship.get("source_ref")
    rel = relationship.get("relationship_type")
    tgt = relationship.get("target_ref")
    if not isinstance(src, str) or not isinstance(rel, str) or not isinstance(tgt, str):
        return None
    return (src, rel, tgt)


@dataclass(frozen=True)
class StixPersistenceFields:
    """Columns derived from a STIX object dict prior to insert."""

    stix_id: str
    stix_type: str
    spec_version: str
    created: datetime | None
    modified: datetime | None
    created_by_ref: str | None
    revoked: bool
    confidence: int | None


def extract_stix_persistence_fields(obj: dict[str, Any]) -> StixPersistenceFields:
    """Map ``obj`` to table columns; ``modified`` is ``None`` for SCO rows."""

    stix_id = obj.get("id")
    if not isinstance(stix_id, str) or not stix_id:
        msg = "STIX object is missing a non-empty string 'id'"
        raise ValueError(msg)

    stix_type = obj.get("type")
    if not isinstance(stix_type, str) or not stix_type:
        msg = "STIX object is missing a non-empty string 'type'"
        raise ValueError(msg)

    spec_version = obj.get("spec_version")
    if not isinstance(spec_version, str) or not spec_version:
        spec_version = "2.1"

    created_raw = obj.get("created")
    if created_raw is None:
        created = None
    else:
        created = parse_stix_datetime(created_raw, field_name="created")

    modified_raw = obj.get("modified")
    modified: datetime | None
    if modified_raw is None:
        modified = None
    else:
        modified = parse_stix_datetime(modified_raw, field_name="modified")

    created_by = obj.get("created_by_ref")
    created_by_ref = created_by if isinstance(created_by, str) else None

    revoked_val = obj.get("revoked", False)
    if not isinstance(revoked_val, bool):
        msg = "STIX 'revoked' must be a boolean when present"
        raise TypeError(msg)

    confidence: int | None
    raw_conf = obj.get("confidence")
    if raw_conf is None:
        confidence = None
    elif isinstance(raw_conf, int):
        confidence = raw_conf
    else:
        msg = "STIX 'confidence' must be an int or null"
        raise TypeError(msg)

    return StixPersistenceFields(
        stix_id=stix_id,
        stix_type=stix_type,
        spec_version=spec_version,
        created=created,
        modified=modified,
        created_by_ref=created_by_ref,
        revoked=revoked_val,
        confidence=confidence,
    )
