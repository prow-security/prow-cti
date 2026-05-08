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

from prow.stix.markings import (
    TLP_AMBER,
    TLP_AMBER_STRICT,
    TLP_CLEAR,
    TLP_GREEN,
    TLP_LEVELS,
    TLP_RED,
    label_to_tlp_id,
    tlp_id_to_label,
)


def test_tlp_constants_are_marking_definition_ids() -> None:
    for value in (TLP_CLEAR, TLP_GREEN, TLP_AMBER, TLP_AMBER_STRICT, TLP_RED):
        assert isinstance(value, str)
        assert value, "TLP constant must be non-empty"
        assert value.startswith("marking-definition--")


def test_tlp_levels_set_contains_exactly_the_five_constants() -> None:
    assert TLP_LEVELS == frozenset({TLP_CLEAR, TLP_GREEN, TLP_AMBER, TLP_AMBER_STRICT, TLP_RED})
    assert len(TLP_LEVELS) == 5


def test_tlp_constants_are_distinct() -> None:
    values = [TLP_CLEAR, TLP_GREEN, TLP_AMBER, TLP_AMBER_STRICT, TLP_RED]
    assert len(set(values)) == len(values)


def test_label_round_trip() -> None:
    labels = ["TLP:CLEAR", "TLP:GREEN", "TLP:AMBER", "TLP:AMBER+STRICT", "TLP:RED"]
    for label in labels:
        stix_id = label_to_tlp_id(label)
        assert stix_id is not None
        assert tlp_id_to_label(stix_id) == label


def test_id_round_trip() -> None:
    for stix_id in TLP_LEVELS:
        label = tlp_id_to_label(stix_id)
        assert label is not None
        assert label_to_tlp_id(label) == stix_id


def test_unknown_id_returns_none() -> None:
    assert tlp_id_to_label("marking-definition--00000000-0000-0000-0000-000000000000") is None
    assert tlp_id_to_label("not-a-stix-id-at-all") is None
    assert tlp_id_to_label("") is None


def test_unknown_label_returns_none() -> None:
    assert label_to_tlp_id("TLP:WHITE") is None  # legacy TLP 1.0 not exposed in Pass A
    assert label_to_tlp_id("tlp:clear") is None  # case-sensitive by design
    assert label_to_tlp_id("UNKNOWN") is None
    assert label_to_tlp_id("") is None
