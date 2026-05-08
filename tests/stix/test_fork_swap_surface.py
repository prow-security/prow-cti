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

"""Surface lock for prow.stix._stix2_adapter.

The adapter is the fork-swap pivot point per ADR-0009 (2026-05-07
amendment). Adding a public callable here changes the contract a
future fork or replacement implementation has to honour. This test
makes any such addition impossible to land silently — the assertion
fails until ``EXPECTED_SURFACE`` is updated, which forces an explicit
design conversation.
"""

from __future__ import annotations

import inspect

import prow.stix._stix2_adapter as adapter

EXPECTED_SURFACE = frozenset(
    {
        "canonical_json_dump",
        "compute_sco_id",
        "parse_stix2_dict",
        "serialise_to_stix2_json",
    }
)


def test_adapter_public_surface_is_locked() -> None:
    actual = frozenset(
        name
        for name, obj in inspect.getmembers(adapter)
        if not name.startswith("_")
        and inspect.isfunction(obj)
        and inspect.getmodule(obj) is adapter
    )
    assert actual == EXPECTED_SURFACE, (
        "prow.stix._stix2_adapter public surface drifted. Adding to it "
        "requires updating ADR-0009's fork-swap surface analysis and "
        "EXPECTED_SURFACE in this test. Removing from it requires checking "
        "every consumer site under prow/. "
        f"Added: {sorted(actual - EXPECTED_SURFACE)}; "
        f"Removed: {sorted(EXPECTED_SURFACE - actual)}."
    )


def test_adapter_dunder_all_matches_expected_surface() -> None:
    assert frozenset(adapter.__all__) == EXPECTED_SURFACE, (
        "_stix2_adapter.__all__ disagrees with the surface lock. Both must change together."
    )
