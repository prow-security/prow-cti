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
(and for the rest of prow). The functions below are pure data
transforms — no I/O, no global state, no logging side effects.

Adding a function to this module requires updating
``tests/stix/test_fork_swap_surface.py`` so the surface lock fails on
the otherwise-silent expansion of the boundary. That guardrail makes
growth of the boundary an explicit, reviewable design decision, not
an accident of feature work.

Per the design note's 2026-05-07 amendment all four functions
delegate to upstream ``stix2`` for v0.1. The delegation centralises
the soft-fork swap point (ADR-0009 amendment): replacing upstream
means rewriting this module, not refactoring across the codebase.
"""

from __future__ import annotations

import uuid
from typing import Any

# `stix2` 3.0.2 does not ship a `py.typed` marker or stubs, so mypy
# cannot infer types across this boundary. We type-ignore the imports
# explicitly (rather than disabling import discovery globally) so the
# missing-stubs status is visible at the one place it matters and does
# not silently shadow real type errors elsewhere.
import stix2  # type: ignore[import-untyped]
import stix2.base  # type: ignore[import-untyped]

__all__ = [
    "canonical_json_dump",
    "compute_sco_id",
    "parse_stix2_dict",
    "serialise_to_stix2_json",
]

# Upstream ``stix2`` exposes its STIX 2.1 SCO determinstic-ID namespace
# UUID and its RFC 8785-based canonicaliser through ``stix2.base``. Both
# are documented under-the-hood building blocks; the maintainers do not
# offer a public top-level alias as of 3.0.2. Pinning the import path
# here keeps the dependence to one line — the rest of prow imports
# nothing from ``stix2`` at all.
_SCO_DET_ID_NAMESPACE = stix2.base.SCO_DET_ID_NAMESPACE
_canonicalize = stix2.base.canonicalize


def serialise_to_stix2_json(prow_object: Any) -> str:
    """Render a prow-owned STIX object to its canonical STIX 2.1 JSON form.

    Round-trips ``prow_object`` through ``stix2`` so the output
    matches what other STIX 2.1 tools expect on the wire (canonical
    key ordering, spec-compliant timestamp formatting, deterministic
    whitespace). The double-conversion (prow → dict → ``stix2`` →
    JSON) is the explicit cost of routing through upstream for v0.1;
    the future fork-or-replace path collapses it to direct
    prow → JSON.

    Args:
        prow_object: Any prow Pydantic model from
            :mod:`prow.stix.types`. The caller is responsible for
            passing in already-validated objects — this function
            does not re-validate.

    Returns:
        A UTF-8 JSON string sorted-keys, no trailing newline. Safe
        to persist as the source-of-truth ``raw`` column or emit
        on the wire.
    """
    data: dict[str, Any] = prow_object.model_dump(mode="json")
    upstream = stix2.parse(data, allow_custom=True)
    serialised = upstream.serialize(pretty=False, sort_keys=True)
    return str(serialised)


def parse_stix2_dict(data: dict[str, Any]) -> Any:
    """Run ``data`` through ``stix2``'s parser and return the upstream object.

    The return value is a ``stix2`` library object — **not** a prow
    Pydantic model. Callers convert the result by passing the
    original ``data`` dict to the matching prow type's
    :meth:`prow.stix.types._StixCommon.parse_external` (or
    :meth:`pydantic.BaseModel.model_validate` if the caller has
    already done JSON Schema validation themselves).

    Pass A's ingestion path runs ``validate_stix_object`` first;
    this function exists for the rare case where prow needs to look
    at the upstream-typed object (e.g. to call a ``stix2`` utility
    that expects its own classes).

    Args:
        data: A pre-parsed STIX object as a Python ``dict``.

    Returns:
        A ``stix2`` library object (``stix2._STIXBase21`` instance).
    """
    return stix2.parse(data, allow_custom=True)


def compute_sco_id(sco_type: str, contributing_properties: dict[str, Any]) -> str:
    """Compute a STIX 2.1 deterministic SCO ID via ``stix2``'s primitives.

    Builds the ID using the same building blocks ``stix2`` itself
    uses inside :meth:`stix2.base._Observable._generate_id` —
    :func:`stix2.base.canonicalize` (RFC 8785 JCS) for the
    contributing-properties dict, then UUIDv5 against
    ``stix2.base.SCO_DET_ID_NAMESPACE``. Output is byte-identical to
    the IDs the ``stix2`` SCO classes produce for the same input.

    The caller is responsible for selecting exactly the spec-mandated
    contributing properties for ``sco_type``; this function does not
    filter, defang, or pick canonical hashes. The
    :mod:`prow.stix.helpers` factory functions encapsulate that
    selection so connector authors do not have to remember which
    properties contribute to each SCO type's ID.

    Args:
        sco_type: The SCO ``type`` value (e.g. ``"ipv4-addr"``,
            ``"file"``, ``"url"``).
        contributing_properties: The subset of the SCO's properties
            that the spec marks as contributing to the deterministic
            ID for that type.

    Returns:
        The full STIX ID string, e.g.
        ``"ipv4-addr--ff26c055-6336-5bc5-b98d-13d6226742dd"``.
    """
    # TODO(post-Pass-B): replace with a native implementation validated
    # against OASIS test vectors. Per ADR-0009's 2026-05-07 amendment
    # the v0.1 commitment is delegation to upstream; native
    # reimplementation is gated on a fork or on the conformance vectors
    # landing in tests/.
    canonical = _canonicalize(contributing_properties, utf8=False)
    digest = uuid.uuid5(_SCO_DET_ID_NAMESPACE, canonical)
    return f"{sco_type}--{digest}"


def canonical_json_dump(data: dict[str, Any]) -> str:
    """Serialise ``data`` as canonical JSON for hashing and signing.

    Uses :func:`stix2.base.canonicalize` (the RFC 8785 JCS
    implementation that ``stix2`` vendors under
    :mod:`stix2.canonicalization.Canonicalize`). This matches the
    canonicalisation ``stix2`` itself applies when computing
    deterministic SCO IDs, which is the whole reason the wrapper
    needs a canonical form: hashes computed here on prow's side
    line up with hashes other STIX 2.1 tools compute on theirs.

    Note: the result is **JCS** canonical JSON specifically; older
    STIX practice sometimes used a plainer
    ``json.dumps(sort_keys=True, separators=(',', ':'))`` shape that
    differs only on numeric corner cases (negative zeros, very
    large floats). We pick JCS because that is what upstream picks.

    Args:
        data: Any JSON-serialisable Python value (typically a STIX
            object dict).

    Returns:
        Canonical JSON as a Python ``str``.
    """
    return str(_canonicalize(data, utf8=False))
