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

"""Connector-facing factory helpers for STIX 2.1 objects.

These are the ``bundle()``, ``indicator()``, ``url_observable()``,
``relationship()`` (and peers) shown in the SDK example code at
``docs/02_CONNECTOR_SDK.md``. They construct the appropriate
:mod:`prow.stix.types` model with sensible defaults so connector
authors can write::

    obs = url_observable(value=row["url"])
    ind = indicator(name="...", pattern=f"[url:value = '{row['url']}']")
    rel = relationship(ind, "based-on", obs)
    await ctx.emit(bundle([obs, ind, rel]))

Helper invariants:

* SDOs / SROs get a fresh UUIDv4-based ``id`` when one is not
  supplied; ``created`` and ``modified`` default to ``now`` (UTC).
* SCOs get the spec-mandated UUIDv5 ``id`` computed via the
  ``_stix2_adapter.compute_sco_id`` boundary, so two helpers called
  with the same observable values produce the same ID — that is what
  enables the deduplicator to do its job.
* ``spec_version`` is always ``"2.1"``.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from prow.stix._stix2_adapter import compute_sco_id
from prow.stix.types import (
    Bundle,
    DomainName,
    EmailAddr,
    File,
    Indicator,
    Ipv4Addr,
    Ipv6Addr,
    Relationship,
    Url,
)

__all__ = [
    "bundle",
    "domain_observable",
    "email_addr_observable",
    "file_observable",
    "indicator",
    "ipv4_observable",
    "ipv6_observable",
    "relationship",
    "url_observable",
]


def _utc_now() -> datetime:
    """Return ``datetime.now(timezone.utc)``; isolated for testability."""
    return datetime.now(UTC)


def _fresh_id(stix_type: str) -> str:
    """Return a fresh ``<type>--<uuid4>`` identifier.

    Used for SDOs, SROs, and Bundles; SCOs route through
    :func:`prow.stix._stix2_adapter.compute_sco_id` instead.
    """
    return f"{stix_type}--{uuid.uuid4()}"


def _ref_of(value: Any) -> str:
    """Coerce a STIX object or string ID to a STIX ID string.

    The ``relationship`` helper accepts either form because connector
    authors sometimes carry full objects through their pipeline and
    sometimes just IDs.
    """
    if isinstance(value, str):
        return value
    if hasattr(value, "id") and isinstance(value.id, str):
        return value.id
    raise TypeError(
        f"expected a STIX object with an 'id' attribute or a string ID, got {type(value).__name__}"
    )


def bundle(objects: Sequence[Any], *, id: str | None = None) -> Bundle:
    """Wrap an ordered sequence of STIX objects in a ``Bundle``.

    Args:
        objects: One or more :mod:`prow.stix.types` instances. Order
            is preserved on the wire, which matters for human
            readability — keep dependencies before dependents (SCOs
            before the SDOs that reference them, SDOs before the SROs
            that link them).
        id: Optional pre-assigned bundle ID. When omitted a fresh
            ``bundle--<uuid4>`` is generated.

    Returns:
        A constructed :class:`Bundle`.
    """
    return Bundle(id=id or _fresh_id("bundle"), objects=list(objects))


def indicator(
    *,
    name: str,
    pattern: str,
    pattern_type: str = "stix",
    indicator_types: Sequence[str] | None = None,
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
    confidence: int | None = None,
    description: str | None = None,
    object_marking_refs: Sequence[str] | None = None,
    created_by_ref: str | None = None,
    id: str | None = None,
) -> Indicator:
    """Build a STIX 2.1 Indicator with safe defaults.

    Args:
        name: Human-readable name for the indicator (required by
            the helper, optional by the spec — connector code
            without a name produces near-useless intel and the
            helper enforces the better default).
        pattern: The detection pattern (STIX patterning by default).
        pattern_type: Pattern grammar; defaults to ``"stix"``.
        indicator_types: Optional list of indicator-type-ov values
            (e.g. ``["malicious-activity"]``).
        valid_from: When the indicator becomes valuable. Defaults
            to ``now`` if omitted.
        valid_until: Optional end of validity window.
        confidence: Optional 0-100 confidence integer.
        description: Optional free-text context.
        object_marking_refs: TLP / statement marking IDs to apply.
        created_by_ref: ID of the identity that created this
            indicator.
        id: Optional pre-assigned indicator ID.

    Returns:
        A constructed :class:`Indicator`.
    """
    now = _utc_now()
    return Indicator(
        id=id or _fresh_id("indicator"),
        created=now,
        modified=now,
        created_by_ref=created_by_ref,
        confidence=confidence,
        object_marking_refs=list(object_marking_refs) if object_marking_refs else None,
        name=name,
        description=description,
        pattern=pattern,
        pattern_type=pattern_type,
        indicator_types=list(indicator_types) if indicator_types else None,
        valid_from=valid_from or now,
        valid_until=valid_until,
    )


def relationship(
    source: Any,
    relationship_type: str,
    target: Any,
    *,
    description: str | None = None,
    confidence: int | None = None,
    object_marking_refs: Sequence[str] | None = None,
    created_by_ref: str | None = None,
    id: str | None = None,
) -> Relationship:
    """Build a STIX 2.1 Relationship between ``source`` and ``target``.

    Args:
        source: A prow STIX object or a STIX ID string.
        relationship_type: The spec-mandated edge label (e.g.
            ``"based-on"``, ``"indicates"``, ``"targets"``).
        target: A prow STIX object or a STIX ID string.
        description: Optional free-text context for the edge.
        confidence: Optional 0-100 confidence integer.
        object_marking_refs: TLP / statement marking IDs.
        created_by_ref: ID of the identity that authored the edge.
        id: Optional pre-assigned relationship ID.

    Returns:
        A constructed :class:`Relationship`.
    """
    now = _utc_now()
    return Relationship(
        id=id or _fresh_id("relationship"),
        created=now,
        modified=now,
        created_by_ref=created_by_ref,
        confidence=confidence,
        object_marking_refs=list(object_marking_refs) if object_marking_refs else None,
        relationship_type=relationship_type,
        source_ref=_ref_of(source),
        target_ref=_ref_of(target),
        description=description,
    )


# ---------------------------------------------------------------------------
# SCO helpers — the deterministic-ID work happens here so connector authors
# never have to think about which properties contribute to the UUIDv5.
# ---------------------------------------------------------------------------


# Hash precedence per STIX 2.1 spec File SCO id-contributing-properties:
# the canonical hash is the first one present in this order. If none of
# these are present, the ID falls back to ``name``.
_FILE_HASH_PRECEDENCE: tuple[str, ...] = (
    "SHA-256",
    "SHA-1",
    "MD5",
    "SHA-512",
    "SHA3-256",
    "SHA3-512",
    "SSDEEP",
    "TLSH",
)


def url_observable(*, value: str) -> Url:
    """Build a STIX URL SCO with a deterministic ID."""
    return Url(id=compute_sco_id("url", {"value": value}), value=value)


def ipv4_observable(*, value: str) -> Ipv4Addr:
    """Build a STIX IPv4 Address SCO with a deterministic ID."""
    return Ipv4Addr(id=compute_sco_id("ipv4-addr", {"value": value}), value=value)


def ipv6_observable(*, value: str) -> Ipv6Addr:
    """Build a STIX IPv6 Address SCO with a deterministic ID."""
    return Ipv6Addr(id=compute_sco_id("ipv6-addr", {"value": value}), value=value)


def domain_observable(*, value: str) -> DomainName:
    """Build a STIX Domain Name SCO with a deterministic ID."""
    return DomainName(id=compute_sco_id("domain-name", {"value": value}), value=value)


def email_addr_observable(*, value: str) -> EmailAddr:
    """Build a STIX Email Address SCO with a deterministic ID."""
    return EmailAddr(id=compute_sco_id("email-addr", {"value": value}), value=value)


def file_observable(
    *,
    hashes: dict[str, str] | None = None,
    name: str | None = None,
    size: int | None = None,
    extensions: dict[str, dict[str, Any]] | None = None,
) -> File:
    """Build a STIX File SCO with a spec-correct deterministic ID.

    The ID-contributing-properties for ``file`` per STIX 2.1 are
    ``hashes``, ``name``, and ``extensions``. When ``hashes`` is
    provided the helper picks the highest-precedence available hash
    (per :data:`_FILE_HASH_PRECEDENCE`) for the ID computation; the
    full ``hashes`` dict still rides on the resulting object. If no
    hashes are provided, ``name`` alone seeds the ID — which yields
    a stable but weak identifier; the caller is expected to know
    that. When ``extensions`` is provided, it participates in the
    ID computation as well, so two files identical in name + hash
    but distinguishable by extension data (e.g. a PE binary versus
    an archive-ext payload) get distinct deterministic IDs.

    Args:
        hashes: Optional mapping of ``{algo: hex}``. At minimum one
            of ``hashes`` or ``name`` must be supplied.
        name: Optional file name.
        size: Optional file size in bytes.
        extensions: Optional mapping of STIX File extensions, keyed
            by extension name (``"archive-ext"``,
            ``"windows-pebinary-ext"``, ``"pdf-ext"``, etc.). Values
            are the extension's property dicts. Passed through to
            the :class:`File` model unchanged and folded into the
            ID-contributing properties so the resulting ID is
            stable across runs and distinct from a same-name +
            same-hash file without these extensions.

    Returns:
        A constructed :class:`File`.

    Raises:
        ValueError: Neither ``hashes`` nor ``name`` was supplied;
            the spec requires at least one ID-contributing property.
    """
    if not hashes and not name:
        raise ValueError("file_observable requires at least one of hashes or name")

    contributing: dict[str, Any] = {}
    if hashes:
        chosen = next((algo for algo in _FILE_HASH_PRECEDENCE if algo in hashes), None)
        if chosen is None:
            # Caller passed hashes the precedence list does not know
            # about; fall back to the dict itself so the ID still
            # reflects the supplied content rather than silently
            # ignoring the hashes.
            contributing["hashes"] = dict(hashes)
        else:
            contributing["hashes"] = {chosen: hashes[chosen]}
    if name:
        contributing["name"] = name
    if extensions:
        contributing["extensions"] = extensions

    return File(
        id=compute_sco_id("file", contributing),
        hashes=hashes,
        name=name,
        size=size,
        extensions=extensions or {},
    )
