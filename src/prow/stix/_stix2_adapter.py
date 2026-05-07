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

"""Sole boundary between :mod:`prow.stix` and the upstream ``stix2`` package.

This module is the **only** place in prow where ``import stix2`` is
permitted. The :file:`importlinter.ini` ``stix-adapter-isolation``
contract enforces that for every other module under :mod:`prow.stix`
(and for the rest of prow). Pass A declares the four function
signatures that the rest of :mod:`prow.stix` will call into; Pass B
provides the bodies and adds the first ``import stix2`` statement.

The functions below are pure data transforms — no I/O, no global
state, no logging side effects. They translate between prow-owned
data (Pydantic models in Pass B; plain ``dict``s and primitives for
now) and ``stix2`` library types.

Adding a function to this module requires updating the fork-swap
surface test that locks the adapter's public callable list. That
guardrail makes growth of the boundary an explicit, reviewable design
decision, not an accident of feature work.

The ``Any`` annotations here are deliberate Pass A placeholders. Pass
B narrows them to the concrete prow Pydantic types once
:mod:`prow.stix.types` exists.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "canonical_json_dump",
    "compute_sco_id",
    "parse_stix2_dict",
    "serialise_to_stix2_json",
]


def serialise_to_stix2_json(prow_object: Any) -> str:
    """Render a prow-owned STIX object to its canonical STIX 2.1 JSON form.

    The Pass B implementation will route ``prow_object`` through the
    ``stix2`` library's serialisation path so the output matches what
    other STIX 2.1 tools expect on the wire (canonical key ordering,
    spec-compliant timestamp formatting, deterministic whitespace).

    Args:
        prow_object: A prow Pydantic model (Pass B) representing any
            SDO, SCO, SRO, SMO, or :class:`Bundle`. Pass A keeps this
            typed as :data:`typing.Any` because the Pydantic types do
            not yet exist.

    Returns:
        A UTF-8 JSON string ready to emit on the wire or persist as
        the source-of-truth ``raw`` column in storage.

    Raises:
        NotImplementedError: Always, in Pass A. Pass B replaces this
            stub with the actual ``stix2`` round-trip.
    """
    raise NotImplementedError("Pass B")


def parse_stix2_dict(data: dict[str, Any]) -> Any:
    """Construct a prow-owned object from a parsed STIX 2.1 dict.

    Pass B will run ``data`` through ``stix2``'s parser to perform
    upstream's library-level checks, then translate the resulting
    ``stix2`` object into the matching prow Pydantic model. JSON
    Schema validation is the responsibility of
    :func:`prow.stix._validate.validate_stix_object` and runs *before*
    this function on the ingest path.

    Args:
        data: A pre-parsed STIX object as a Python ``dict``. May be a
            single SDO/SCO/SRO/SMO or a bundle.

    Returns:
        The corresponding prow Pydantic instance — concrete type
        decided by the ``type`` discriminator. Pass A keeps the
        return type as :data:`typing.Any`.

    Raises:
        NotImplementedError: Always, in Pass A.
    """
    raise NotImplementedError("Pass B")


def compute_sco_id(sco_type: str, contributing_properties: dict[str, Any]) -> str:
    """Compute a STIX 2.1 deterministic SCO ID for ``sco_type``.

    Per the v0.1 design (ADR-0009 amendment), this function
    *delegates to* the ``stix2`` library's identifier-generation
    utility rather than reimplementing the UUIDv5 namespace algorithm
    from STIX 2.1 Part 3. Hand-rolled UUIDv5 logic is on the v0.2+
    backlog only if upstream stalls or proves wrong on conformance
    vectors.

    Args:
        sco_type: The SCO ``type`` value (e.g. ``"ipv4-addr"``,
            ``"file"``, ``"url"``).
        contributing_properties: The subset of the SCO's properties
            that the spec marks as contributing to the deterministic
            ID for that type. Callers are responsible for supplying
            exactly the spec-mandated set; this function does not
            filter.

    Returns:
        The full STIX ID string, e.g.
        ``"ipv4-addr--ff26c055-6336-5bc5-b98d-13d6226742dd"``.

    Raises:
        NotImplementedError: Always, in Pass A.
    """
    raise NotImplementedError("Pass B")


def canonical_json_dump(data: dict[str, Any]) -> str:
    """Serialise ``data`` as canonical JSON for hashing and signing.

    Canonical JSON gives deterministic byte output across processes
    and platforms — sorted keys, no extraneous whitespace, fixed
    number formatting, UTF-8 — which the ingestion pipeline needs for
    deduplication hashes and the federation layer needs for signed
    bundle transport.

    Pass B will pin the exact canonicalisation scheme to whatever
    ``stix2`` (or a conformant equivalent) emits so prow's hashes
    match other STIX 2.1 tools' hashes for the same logical object.

    Args:
        data: The STIX object as a Python ``dict``.

    Returns:
        A canonical JSON string suitable for hashing, signing, or
        byte-level comparison.

    Raises:
        NotImplementedError: Always, in Pass A.
    """
    raise NotImplementedError("Pass B")
