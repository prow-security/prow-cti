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

"""Validate STIX bundles and persist accepted objects (connector-agnostic)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from prow.connector.protocol.messages import EmitAckPayload, ValidationFailure
from prow.db.repositories import (
    DEFAULT_INSERT_BATCH_SIZE,
    SqlAlchemyStixObjectRepository,
)
from prow.stix._validate import StixValidationError, validate_stix_object


def stix_validation_error_to_failures(err: StixValidationError) -> list[ValidationFailure]:
    """Convert :class:`StixValidationError` into protocol-shaped failures."""

    source = err.source if isinstance(err.source, dict) else {}
    object_id = source.get("id")
    oid = object_id if isinstance(object_id, str) and object_id else "unknown"
    return [ValidationFailure(object_id=oid, error=msg) for msg in err.errors]


def validate_and_partition_bundle(
    bundle: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[ValidationFailure]]:
    """Validate bundle envelope and each object; return ``(valid_objects, failures)``."""

    failures: list[ValidationFailure] = []
    if not isinstance(bundle, dict):
        failures.append(
            ValidationFailure(object_id="unknown", error="bundle must be a JSON object"),
        )
        return [], failures

    if bundle.get("type") != "bundle":
        failures.append(
            ValidationFailure(
                object_id=str(bundle.get("id", "unknown")),
                error="bundle 'type' must be 'bundle'",
            ),
        )
        return [], failures

    bundle_id = bundle.get("id")
    if not isinstance(bundle_id, str) or not bundle_id:
        failures.append(
            ValidationFailure(object_id="unknown", error="bundle is missing a non-empty 'id'"),
        )
        return [], failures

    raw_objects = bundle.get("objects")
    if not isinstance(raw_objects, list):
        failures.append(
            ValidationFailure(object_id=bundle_id, error="bundle 'objects' must be an array"),
        )
        return [], failures

    valid: list[dict[str, Any]] = []
    for index, item in enumerate(raw_objects):
        if not isinstance(item, dict):
            failures.append(
                ValidationFailure(
                    object_id=bundle_id,
                    error=f"objects/{index}: expected object, got {type(item).__name__}",
                ),
            )
            continue
        try:
            validate_stix_object(item)
        except StixValidationError as err:
            object_id = item.get("id")
            oid = object_id if isinstance(object_id, str) and object_id else bundle_id
            failures.extend(ValidationFailure(object_id=oid, error=msg) for msg in err.errors)
            continue
        valid.append(item)

    return valid, failures


async def ingest_stix_bundle(
    session: AsyncSession,
    bundle: dict[str, Any],
    *,
    source_connector_instance_id: str,
    batch_size: int = DEFAULT_INSERT_BATCH_SIZE,
) -> EmitAckPayload:
    """Validate ``bundle`` outside any DB transaction, then persist valid objects once.

    ``session`` must not already be in a write transaction; this function calls
    :meth:`sqlalchemy.ext.asyncio.AsyncSession.begin` for the insert phase.
    """

    valid_objects, validation_failures = validate_and_partition_bundle(bundle)
    if not valid_objects:
        return EmitAckPayload(accepted=0, duplicates=0, validation_failures=validation_failures)

    async with session.begin():
        repo = SqlAlchemyStixObjectRepository(session)
        accepted, duplicates = await repo.bulk_insert_dedupe(
            valid_objects,
            source_connector_instance_id=source_connector_instance_id,
            batch_size=batch_size,
        )

    return EmitAckPayload(
        accepted=accepted,
        duplicates=duplicates,
        validation_failures=validation_failures,
    )
