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

"""Conformance: vendored OASIS example bundles round-trip through prow.

For each ``examples/*.json`` file vendored under
``tests/stix/fixtures/oasis_examples/``:

1. The file passes prow's JSON Schema validation
   (:func:`prow.stix.validate_stix_object`).
2. For every contained STIX object whose type is in
   :data:`tests.stix._helpers.MODELLED_TYPES`, the object round-trips
   through the matching prow Pydantic model: ``parse_external``,
   ``model_dump_json``, then a STIX-equivalence check against the
   original.

Object types that prow does not yet model (``course-of-action``,
``infrastructure``) are noted explicitly in the assertion failure
text but do not fail the test — they tell the maintainer which types
to add when expanding the modelled set.
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

import pytest

from prow.stix import validate_stix_object
from prow.stix.types import Bundle
from tests.stix._helpers import MODELLED_TYPES, stix_equivalent

EXAMPLES_DIR = resources.files("tests.stix") / "fixtures" / "oasis_examples"


def _collect_example_files() -> list[str]:
    """Return relative paths to every example JSON file (sorted)."""
    paths: list[str] = []
    for child in EXAMPLES_DIR.iterdir():
        if child.is_dir():
            for grandchild in child.iterdir():
                if grandchild.is_file() and grandchild.name.endswith(".json"):
                    paths.append(f"{child.name}/{grandchild.name}")
        elif child.is_file() and child.name.endswith(".json"):
            paths.append(child.name)
    return sorted(paths)


EXAMPLE_FILES = _collect_example_files()


def _load(rel_path: str) -> dict[str, Any]:
    parts = rel_path.split("/")
    target = EXAMPLES_DIR
    for part in parts:
        target = target / part
    raw = target.read_text(encoding="utf-8")
    return json.loads(raw)  # type: ignore[no-any-return]


def test_example_corpus_is_non_empty() -> None:
    assert EXAMPLE_FILES, (
        "no OASIS example fixtures found; vendor refresh missed tests/stix/fixtures/oasis_examples/"
    )


@pytest.mark.parametrize("example_path", EXAMPLE_FILES)
def test_example_passes_json_schema(example_path: str) -> None:
    data = _load(example_path)
    validate_stix_object(data)


@pytest.mark.parametrize("example_path", EXAMPLE_FILES)
def test_example_objects_round_trip_through_models(example_path: str) -> None:
    data = _load(example_path)

    if data.get("type") == "bundle":
        objects: list[dict[str, Any]] = list(data.get("objects", []))
    else:
        objects = [data]

    unmodelled_types: set[str] = set()
    for index, obj in enumerate(objects):
        stix_type = obj.get("type")
        model_cls = MODELLED_TYPES.get(stix_type) if isinstance(stix_type, str) else None
        if model_cls is None:
            assert isinstance(stix_type, str), (
                f"object {index} in {example_path} has non-string type: {stix_type!r}"
            )
            unmodelled_types.add(stix_type)
            continue

        instance = model_cls.model_validate(obj)
        roundtrip = json.loads(instance.model_dump_json())
        assert stix_equivalent(obj, roundtrip), (
            f"round-trip mismatch for {example_path}::objects[{index}] "
            f"(type={stix_type})\n"
            f"original: {json.dumps(obj, indent=2, sort_keys=True)}\n"
            f"round:    {json.dumps(roundtrip, indent=2, sort_keys=True)}"
        )

    if unmodelled_types:
        # Not a failure — informational only. pytest captures the print
        # and shows it on -v / -rA, signalling which types still need
        # wrapper coverage. Conformance "passes" once every modelled
        # object round-trips; unmodelled types are tracked elsewhere.
        print(
            f"INFO: {example_path} contains unmodelled STIX types "
            f"(skipped per-object round-trip): {sorted(unmodelled_types)}"
        )


def test_indicator_for_c2_round_trips_via_bundle_helper() -> None:
    """End-to-end Bundle.parse_external on a representative example.

    The per-object test above exercises individual types; this test
    covers the bundle-level path the persister will actually use.
    """
    data = _load("indicator-for-c2-ip-address.json")
    parsed = Bundle.parse_external(data)
    roundtrip = json.loads(parsed.model_dump_json())
    assert stix_equivalent(data, roundtrip)
