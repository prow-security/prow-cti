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

import copy
import json
import time
from importlib import resources
from typing import Any

import pytest

from prow.stix._validate import (
    StixValidationError,
    validate_many,
    validate_stix_object,
)

FIXTURES = resources.files("tests.stix") / "fixtures"


def _load_indicator() -> dict[str, Any]:
    raw = (FIXTURES / "valid_indicator.json").read_text(encoding="utf-8")
    return json.loads(raw)  # type: ignore[no-any-return]


def test_valid_indicator_passes() -> None:
    validate_stix_object(_load_indicator())


def test_indicator_missing_required_field_fails() -> None:
    obj = _load_indicator()
    del obj["pattern"]

    with pytest.raises(StixValidationError) as excinfo:
        validate_stix_object(obj)

    err = excinfo.value
    assert err.errors, "errors list must be non-empty"
    assert any("pattern" in line for line in err.errors)
    assert err.source is obj


def test_indicator_with_wrong_created_type_fails() -> None:
    obj = _load_indicator()
    obj["created"] = "not-a-timestamp"

    with pytest.raises(StixValidationError) as excinfo:
        validate_stix_object(obj)

    assert any("created" in line for line in excinfo.value.errors)


def test_unknown_type_fails_with_clear_error() -> None:
    obj = {"type": "definitely-not-a-stix-type"}

    with pytest.raises(StixValidationError) as excinfo:
        validate_stix_object(obj)

    assert any("unknown STIX type" in line for line in excinfo.value.errors)


def test_unknown_type_passes_with_allow_custom_types() -> None:
    obj = {
        "type": "x-mitre-tactic",
        "id": "x-mitre-tactic--8e496ffb-9bcf-43e6-8272-ecb390143907",
        "spec_version": "2.1",
    }
    validate_stix_object(obj, allow_custom_types=True)


def test_unknown_type_malformed_id_fails_with_allow_custom_types() -> None:
    obj = {
        "type": "x-mitre-tactic",
        "id": "not-a-valid-stix-id",
        "spec_version": "2.1",
    }
    with pytest.raises(StixValidationError) as excinfo:
        validate_stix_object(obj, allow_custom_types=True)
    assert any("id" in line for line in excinfo.value.errors)


def test_bundle_with_invalid_member_fails_with_indexed_path() -> None:
    good = _load_indicator()
    bad = copy.deepcopy(good)
    del bad["pattern"]

    bundle = {
        "type": "bundle",
        "id": "bundle--cf20f99b-3ed2-4cf1-8a93-d40c9b6b8d95",
        "objects": [good, bad],
    }

    with pytest.raises(StixValidationError) as excinfo:
        validate_stix_object(bundle)

    paths = "\n".join(excinfo.value.errors)
    assert "objects/1" in paths
    assert "pattern" in paths


def test_validate_many_short_circuits_on_first_failure() -> None:
    good = _load_indicator()
    bad = copy.deepcopy(good)
    del bad["pattern"]

    with pytest.raises(StixValidationError):
        validate_many([good, bad, good])


def test_repeat_validation_is_fast() -> None:
    """Smoke check that compiled validators are reused across calls.

    The 2-second ceiling is a deliberately loose smoke check, not the
    10k-indicator / 5-second performance budget — Pass B owns that
    measurement. This test exists to fail loudly if a regression
    starts re-compiling the validator on every call.
    """
    obj = _load_indicator()
    start = time.perf_counter()
    for _ in range(1000):
        validate_stix_object(obj)
    elapsed = time.perf_counter() - start
    assert elapsed < 2.0, f"1000 validations took {elapsed:.2f}s; expected < 2s"
