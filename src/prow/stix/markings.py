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

"""Well-known STIX 2.1 marking-definition identifiers.

This module is the public source of truth for TLP marking-definition
IDs used inside prow. Connectors, tests, and the eventual TLP
propagation logic in the ingestion pipeline reference these constants
instead of pasting raw UUID strings into business logic.

The IDs below are the TLP 2.0 marking-definition objects published by
OASIS at
``oasis-open/cti-stix-common-objects/extension-definition-specifications/tlp-2.0``.
TLP 2.0 was released by FIRST in August 2022 and is the current
recommended labelling scheme for CTI sharing; it replaces the TLP 1.0
marking objects defined in STIX 2.1 specification Appendix B.1
(``TLP:WHITE`` etc.). The TLP 1.0 IDs are not exported from Pass A —
support for ingesting legacy TLP 1.0 markings can be added in a
follow-up if a connector needs it.

Statement and copyright marking objects are not exported. The STIX
2.1 spec defines those as marking *types*, not as specific well-known
instances with fixed UUIDs, so there is nothing to pin here.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "TLP_2_0_EXTENSION_DEFINITION_ID",
    "TLP_AMBER",
    "TLP_AMBER_STRICT",
    "TLP_CLEAR",
    "TLP_GREEN",
    "TLP_LEVELS",
    "TLP_RED",
    "label_to_tlp_id",
    "tlp_id_to_label",
]

TLP_CLEAR: Final[str] = "marking-definition--94868c89-83c2-464b-929b-a1a8aa3c8487"
"""TLP:CLEAR (TLP 2.0). Source: cti-stix-common-objects examples/tlp-clear.json."""

TLP_GREEN: Final[str] = "marking-definition--bab4a63c-aed9-4cf5-a766-dfca5abac2bb"
"""TLP:GREEN (TLP 2.0). Source: cti-stix-common-objects examples/tlp-green.json."""

TLP_AMBER: Final[str] = "marking-definition--55d920b0-5e8b-4f79-9ee9-91f868d9b421"
"""TLP:AMBER (TLP 2.0). Source: cti-stix-common-objects examples/tlp-amber.json."""

TLP_AMBER_STRICT: Final[str] = "marking-definition--939a9414-2ddd-4d32-a0cd-375ea402b003"
"""TLP:AMBER+STRICT (TLP 2.0). Source: cti-stix-common-objects examples/tlp-amber+strict.json."""

TLP_RED: Final[str] = "marking-definition--e828b379-4e03-4974-9ac4-e53a884c97c1"
"""TLP:RED (TLP 2.0). Source: cti-stix-common-objects examples/tlp-red.json."""

TLP_2_0_EXTENSION_DEFINITION_ID: Final[str] = (
    "extension-definition--60a3c5c5-0d10-413e-aab3-9e08dde9e88d"
)
"""ID of the OASIS-published TLP 2.0 extension definition object.

Marking definitions that follow TLP 2.0 carry an ``extensions`` entry
keyed on this ID; downstream code that wants to differentiate TLP 2.0
markings from TLP 1.0 markings checks for this key."""

TLP_LEVELS: Final[frozenset[str]] = frozenset(
    {TLP_CLEAR, TLP_GREEN, TLP_AMBER, TLP_AMBER_STRICT, TLP_RED}
)
"""All five TLP 2.0 marking-definition IDs as a frozenset.

Useful for membership checks like ``ref in TLP_LEVELS`` when filtering
``object_marking_refs`` arrays."""

_ID_TO_LABEL: Final[dict[str, str]] = {
    TLP_CLEAR: "TLP:CLEAR",
    TLP_GREEN: "TLP:GREEN",
    TLP_AMBER: "TLP:AMBER",
    TLP_AMBER_STRICT: "TLP:AMBER+STRICT",
    TLP_RED: "TLP:RED",
}

_LABEL_TO_ID: Final[dict[str, str]] = {label: stix_id for stix_id, label in _ID_TO_LABEL.items()}


def tlp_id_to_label(stix_id: str) -> str | None:
    """Map a well-known TLP marking-definition ID to its canonical label.

    Args:
        stix_id: A STIX ``marking-definition--…`` identifier.

    Returns:
        The canonical TLP label (``"TLP:CLEAR"``, ``"TLP:GREEN"``,
        ``"TLP:AMBER"``, ``"TLP:AMBER+STRICT"``, ``"TLP:RED"``) when
        ``stix_id`` is one of the five well-known TLP 2.0 IDs;
        ``None`` for anything else, including TLP 1.0 IDs and custom
        marking definitions. Returning ``None`` is the documented
        signal for "not a recognised TLP 2.0 marking" — callers
        should not treat it as an error.
    """
    return _ID_TO_LABEL.get(stix_id)


def label_to_tlp_id(label: str) -> str | None:
    """Map a canonical TLP label to its well-known marking-definition ID.

    Labels are matched case-sensitively against the canonical forms
    (``"TLP:CLEAR"`` etc.). Lower-case or mixed-case input returns
    ``None`` deliberately — the spec uses upper-case labels and we do
    not want connectors emitting normalized-but-non-spec strings.

    Args:
        label: A canonical TLP label string.

    Returns:
        The full STIX marking-definition ID for the matching TLP 2.0
        level; ``None`` if ``label`` is not a recognised TLP 2.0
        label.
    """
    return _LABEL_TO_ID.get(label)
