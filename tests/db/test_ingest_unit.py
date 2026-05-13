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

from prow.connector.protocol.messages import ValidationFailure
from prow.db.ingest import stix_validation_error_to_failures, validate_and_partition_bundle
from prow.stix._validate import StixValidationError


def test_stix_validation_error_to_failures_uses_object_id() -> None:
    src = {"id": "indicator--bad", "type": "indicator"}
    err = StixValidationError(["path/to/field: boom"], source=src)
    failures = stix_validation_error_to_failures(err)
    assert failures == [
        ValidationFailure(object_id="indicator--bad", error="path/to/field: boom"),
    ]


def test_stix_validation_error_to_failures_unknown_id() -> None:
    err = StixValidationError(["root: broken"], source={"type": "indicator"})
    failures = stix_validation_error_to_failures(err)
    assert failures[0].object_id == "unknown"


def test_validate_and_partition_bundle_mixed_valid_invalid() -> None:
    good = {
        "type": "indicator",
        "spec_version": "2.1",
        "id": "indicator--8e2e2d2b-17d4-4cbf-938f-98ee46b3cd3f",
        "created": "2024-01-01T12:00:00.000Z",
        "modified": "2024-01-01T12:00:00.000Z",
        "pattern": "[ipv4-addr:value = '198.51.100.7']",
        "pattern_type": "stix",
        "valid_from": "2024-01-01T12:00:00.000Z",
    }
    bad = {"type": "indicator", "id": "indicator--missing-fields"}
    bundle = {
        "type": "bundle",
        "id": "bundle--test",
        "objects": [good, bad],
    }
    valid, failures = validate_and_partition_bundle(bundle)
    assert len(valid) == 1
    assert valid[0]["id"] == good["id"]
    assert failures
    assert all(isinstance(f, ValidationFailure) for f in failures)


def test_validate_bundle_envelope_rejects_non_bundle() -> None:
    valid, failures = validate_and_partition_bundle({"type": "indicator", "id": "x"})
    assert valid == []
    assert failures and "bundle" in failures[0].error.lower()
