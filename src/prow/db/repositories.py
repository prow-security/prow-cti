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

"""Repository protocols and SQLAlchemy implementations."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from prow.db.models import ConnectorStateRow, StixObjectRow
from prow.db.stix_fields import extract_stix_persistence_fields

DEFAULT_INSERT_BATCH_SIZE = 500


def _row_dict(
    obj: dict[str, Any],
    *,
    source_connector_instance_id: str,
) -> dict[str, Any]:
    fields = extract_stix_persistence_fields(obj)
    created = fields.created if fields.created is not None else datetime(1970, 1, 1, tzinfo=UTC)
    return {
        "id": fields.stix_id,
        "type": fields.stix_type,
        "spec_version": fields.spec_version,
        "created": created,
        "modified": fields.modified,
        "created_by_ref": fields.created_by_ref,
        "revoked": fields.revoked,
        "confidence": fields.confidence,
        "source_connector_instance_id": source_connector_instance_id,
        "raw": obj,
    }


@runtime_checkable
class StixObjectRepository(Protocol):
    """Write-side contract for STIX object persistence."""

    async def bulk_insert_dedupe(
        self,
        objects: Sequence[dict[str, Any]],
        *,
        source_connector_instance_id: str,
        batch_size: int = DEFAULT_INSERT_BATCH_SIZE,
    ) -> tuple[int, int]:
        """Insert objects with ON CONFLICT DO NOTHING; return ``(accepted, duplicates)``."""

    async def list_objects(
        self, *, stix_type: str | None = None, limit: int = 100, offset: int = 0
    ) -> tuple[list[dict[str, Any]], int]: ...

    async def get_object(self, stix_id: str) -> dict[str, Any] | None: ...

    async def search_by_observable(
        self, query: str, *, stix_type: str | None = None, limit: int = 50
    ) -> tuple[list[dict[str, Any]], int]: ...

    async def full_text_search(
        self, query: str, *, stix_type: str | None = None, limit: int = 50
    ) -> tuple[list[dict[str, Any]], int]: ...

    async def get_ingest_stats(self) -> dict[str, Any]: ...


@runtime_checkable
class RelationshipRepository(Protocol):
    """Read-side contract for STIX relationships."""

    async def get_relationships(self, stix_id: str) -> list[dict[str, Any]]: ...


@runtime_checkable
class ConnectorStateRepository(Protocol):
    """Durable connector key/value state."""

    async def get(self, instance_id: str, key: str) -> Any | None: ...

    async def set(self, instance_id: str, key: str, value: Any) -> None: ...


class SqlAlchemyStixObjectRepository:
    """Postgres-backed :class:`StixObjectRepository` using partial unique indexes."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def bulk_insert_dedupe(
        self,
        objects: Sequence[dict[str, Any]],
        *,
        source_connector_instance_id: str,
        batch_size: int = DEFAULT_INSERT_BATCH_SIZE,
    ) -> tuple[int, int]:
        if batch_size < 1:
            msg = "batch_size must be >= 1"
            raise ValueError(msg)

        versioned: list[dict[str, Any]] = []
        scos: list[dict[str, Any]] = []
        for obj in objects:
            row = _row_dict(obj, source_connector_instance_id=source_connector_instance_id)
            if row["modified"] is None:
                scos.append(row)
            else:
                versioned.append(row)

        versioned_accepted = await self._insert_batches(
            versioned,
            batch_size=batch_size,
            index_elements=["id", "modified"],
            index_where=sa.text("modified IS NOT NULL"),
        )
        versioned_duplicates = len(versioned) - versioned_accepted

        sco_accepted = await self._insert_batches(
            scos,
            batch_size=batch_size,
            index_elements=["id"],
            index_where=sa.text("modified IS NULL"),
        )
        sco_duplicates = len(scos) - sco_accepted

        return versioned_accepted + sco_accepted, versioned_duplicates + sco_duplicates

    async def list_objects(
        self, *, stix_type: str | None = None, limit: int = 100, offset: int = 0
    ) -> tuple[list[dict[str, Any]], int]:
        stmt = select(StixObjectRow.raw)
        count_stmt = select(sa.func.count()).select_from(StixObjectRow)
        if stix_type:
            stmt = stmt.where(StixObjectRow.type == stix_type)
            count_stmt = count_stmt.where(StixObjectRow.type == stix_type)

        stmt = stmt.order_by(StixObjectRow.created.desc()).limit(limit).offset(offset)

        total = await self._session.scalar(count_stmt) or 0
        result = await self._session.scalars(stmt)
        return list(result.all()), total

    async def get_object(self, stix_id: str) -> dict[str, Any] | None:
        stmt = (
            select(StixObjectRow.raw)
            .where(StixObjectRow.id == stix_id)
            .order_by(StixObjectRow.modified.desc().nulls_last())
            .limit(1)
        )
        return await self._session.scalar(stmt)

    async def search_by_observable(
        self, query: str, *, stix_type: str | None = None, limit: int = 50
    ) -> tuple[list[dict[str, Any]], int]:
        stmt = select(StixObjectRow.raw).where(
            sa.or_(
                StixObjectRow.raw.op("->>")("value") == query,
                StixObjectRow.raw.op("->>")("pattern").like(f"%{query}%"),
            )
        )
        count_stmt = (
            select(sa.func.count())
            .select_from(StixObjectRow)
            .where(
                sa.or_(
                    StixObjectRow.raw.op("->>")("value") == query,
                    StixObjectRow.raw.op("->>")("pattern").like(f"%{query}%"),
                )
            )
        )
        if stix_type:
            stmt = stmt.where(StixObjectRow.type == stix_type)
            count_stmt = count_stmt.where(StixObjectRow.type == stix_type)

        stmt = stmt.limit(limit)

        total = await self._session.scalar(count_stmt) or 0
        result = await self._session.scalars(stmt)
        return list(result.all()), total

    async def full_text_search(
        self, query: str, *, stix_type: str | None = None, limit: int = 50
    ) -> tuple[list[dict[str, Any]], int]:
        stmt = select(StixObjectRow.raw).where(
            sa.or_(
                StixObjectRow.raw.op("->>")("name").ilike(f"%{query}%"),
                StixObjectRow.raw.op("->>")("description").ilike(f"%{query}%"),
            )
        )
        count_stmt = (
            select(sa.func.count())
            .select_from(StixObjectRow)
            .where(
                sa.or_(
                    StixObjectRow.raw.op("->>")("name").ilike(f"%{query}%"),
                    StixObjectRow.raw.op("->>")("description").ilike(f"%{query}%"),
                )
            )
        )
        if stix_type:
            stmt = stmt.where(StixObjectRow.type == stix_type)
            count_stmt = count_stmt.where(StixObjectRow.type == stix_type)

        stmt = stmt.limit(limit)

        total = await self._session.scalar(count_stmt) or 0
        result = await self._session.scalars(stmt)
        return list(result.all()), total

    async def get_ingest_stats(self) -> dict[str, Any]:
        total_stmt = select(sa.func.count()).select_from(StixObjectRow)
        total = await self._session.scalar(total_stmt) or 0

        type_stmt = select(StixObjectRow.type, sa.func.count()).group_by(StixObjectRow.type)
        type_result = await self._session.execute(type_stmt)
        by_type = {row[0]: row[1] for row in type_result.all()}

        last_stmt = select(sa.func.max(StixObjectRow.ingested_at))
        last_ingested = await self._session.scalar(last_stmt)

        return {"total_objects": total, "by_type": by_type, "last_ingested_at": last_ingested}

    async def _insert_batches(
        self,
        rows: list[dict[str, Any]],
        *,
        batch_size: int,
        index_elements: list[str],
        index_where: sa.TextClause,
    ) -> int:
        table = StixObjectRow
        inserted_total = 0
        for start in range(0, len(rows), batch_size):
            chunk = rows[start : start + batch_size]
            insert_stmt = pg_insert(table).values(chunk)
            stmt = insert_stmt.on_conflict_do_nothing(
                index_elements=index_elements,
                index_where=index_where,
            ).returning(StixObjectRow.row_id)
            result = await self._session.execute(stmt)
            inserted_total += len(result.fetchall())
        return inserted_total


class SqlAlchemyRelationshipRepository:
    """Postgres-backed :class:`RelationshipRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_relationships(self, stix_id: str) -> list[dict[str, Any]]:
        stmt = select(StixObjectRow.raw).where(
            StixObjectRow.type == "relationship",
            sa.or_(
                StixObjectRow.raw.op("->>")("source_ref") == stix_id,
                StixObjectRow.raw.op("->>")("target_ref") == stix_id,
            ),
        )
        result = await self._session.scalars(stmt)
        return list(result.all())


class SqlAlchemyConnectorStateRepository:
    """Postgres-backed :class:`ConnectorStateRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, instance_id: str, key: str) -> Any | None:
        stmt = select(ConnectorStateRow.value).where(
            ConnectorStateRow.connector_instance_id == instance_id,
            ConnectorStateRow.key == key,
        )
        return await self._session.scalar(stmt)

    async def set(self, instance_id: str, key: str, value: Any) -> None:
        now = datetime.now(UTC)
        table = ConnectorStateRow
        row = {
            "connector_instance_id": instance_id,
            "key": key,
            "value": value,
            "updated_at": now,
        }
        insert_stmt = pg_insert(table).values(row)
        stmt = insert_stmt.on_conflict_do_update(
            index_elements=["connector_instance_id", "key"],
            set_={
                "value": insert_stmt.excluded.value,
                "updated_at": insert_stmt.excluded.updated_at,
            },
        )
        await self._session.execute(stmt)
