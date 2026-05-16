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
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol, runtime_checkable

import sqlalchemy as sa
from sqlalchemy import Date, func, or_, select
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


def _stix_row_to_public_dict(row: StixObjectRow) -> dict[str, Any]:
    """Merge persisted columns into ``raw`` for API / bundle consumers."""
    out = dict(row.raw)
    out["id"] = row.id
    out["type"] = row.type
    out["spec_version"] = row.spec_version
    out["created"] = row.created
    if row.modified is not None:
        out["modified"] = row.modified
    out["revoked"] = row.revoked
    if row.created_by_ref is not None:
        out["created_by_ref"] = row.created_by_ref
    if row.confidence is not None:
        out["confidence"] = row.confidence
    out["source_connector_instance_id"] = row.source_connector_instance_id
    out["ingested_at"] = row.ingested_at.isoformat()
    return out


@runtime_checkable
class StixObjectRepository(Protocol):
    """STIX object persistence and read APIs used by the HTTP surface."""

    async def bulk_insert_dedupe(
        self,
        objects: Sequence[dict[str, Any]],
        *,
        source_connector_instance_id: str,
        batch_size: int = DEFAULT_INSERT_BATCH_SIZE,
    ) -> tuple[int, int]:
        """Insert objects with ON CONFLICT DO NOTHING; return ``(accepted, duplicates)``."""

    async def list_objects(
        self,
        *,
        stix_type: str | None,
        limit: int,
        offset: int,
        sort: str,
    ) -> tuple[list[dict[str, Any]], int]: ...

    async def get_object(self, stix_id: str) -> dict[str, Any] | None: ...

    async def search_by_observable(
        self,
        q: str,
        *,
        stix_type: str | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]: ...

    async def full_text_search(
        self,
        q: str,
        *,
        stix_type: str | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]: ...

    async def get_ingest_stats(self) -> dict[str, Any]: ...

    async def get_ingest_timeseries(self, *, days: int) -> dict[str, Any]: ...


@runtime_checkable
class RelationshipRepository(Protocol):
    """Read relationships stored as STIX SRO rows in ``stix_objects``."""

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

    async def list_objects(
        self,
        *,
        stix_type: str | None,
        limit: int,
        offset: int,
        sort: str = "ingested_at_desc",
    ) -> tuple[list[dict[str, Any]], int]:
        count_stmt = select(func.count()).select_from(StixObjectRow)
        stmt = select(StixObjectRow).limit(limit).offset(offset)
        order: tuple[Any, ...]
        if sort == "confidence_desc":
            order = (
                StixObjectRow.confidence.desc().nulls_last(),
                StixObjectRow.ingested_at.desc(),
            )
        elif sort == "created_desc":
            order = (StixObjectRow.created.desc(),)
        else:
            order = (StixObjectRow.ingested_at.desc(),)
        stmt = stmt.order_by(*order)
        if stix_type is not None:
            count_stmt = count_stmt.where(StixObjectRow.type == stix_type)
            stmt = stmt.where(StixObjectRow.type == stix_type)

        total = int(await self._session.scalar(count_stmt) or 0)
        rows = (await self._session.scalars(stmt)).all()
        return [_stix_row_to_public_dict(r) for r in rows], total

    async def get_object(self, stix_id: str) -> dict[str, Any] | None:
        stmt = (
            select(StixObjectRow)
            .where(StixObjectRow.id == stix_id)
            .order_by(
                StixObjectRow.modified.desc().nulls_last(),
                StixObjectRow.row_id.desc(),
            )
            .limit(1)
        )
        row = await self._session.scalar(stmt)
        if row is None:
            return None
        return _stix_row_to_public_dict(row)

    async def search_by_observable(
        self,
        q: str,
        *,
        stix_type: str | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        clauses: list[Any] = []
        if stix_type is None or stix_type == "indicator":
            clauses.append(
                sa.and_(
                    StixObjectRow.type == "indicator",
                    StixObjectRow.raw["pattern"].as_string().ilike(f"%{q}%"),
                )
            )
        if stix_type is None or stix_type == "vulnerability":
            clauses.append(
                sa.and_(
                    StixObjectRow.type == "vulnerability",
                    StixObjectRow.raw["name"].as_string().ilike(f"%{q}%"),
                )
            )
        if stix_type is None or stix_type == "ipv4-addr":
            clauses.append(
                sa.and_(
                    StixObjectRow.type == "ipv4-addr",
                    StixObjectRow.raw["value"].as_string() == q,
                )
            )
        if not clauses:
            return [], 0

        stmt = (
            select(StixObjectRow)
            .where(or_(*clauses))
            .order_by(StixObjectRow.ingested_at.desc())
            .limit(limit)
        )
        rows = (await self._session.scalars(stmt)).all()
        return [_stix_row_to_public_dict(r) for r in rows], len(rows)

    async def full_text_search(
        self,
        q: str,
        *,
        stix_type: str | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        blob = sa.cast(StixObjectRow.raw, sa.Text)
        stmt = (
            select(StixObjectRow)
            .where(blob.ilike(f"%{q}%"))
            .order_by(StixObjectRow.ingested_at.desc())
            .limit(limit)
        )
        if stix_type is not None:
            stmt = stmt.where(StixObjectRow.type == stix_type)
        rows = (await self._session.scalars(stmt)).all()
        return [_stix_row_to_public_dict(r) for r in rows], len(rows)

    async def get_ingest_stats(self) -> dict[str, Any]:
        type_stmt = select(StixObjectRow.type, func.count()).group_by(StixObjectRow.type)
        result = await self._session.execute(type_stmt)
        by_type: dict[str, int] = {t: int(c) for t, c in result.all()}
        total_objects = sum(by_type.values())
        last_ingested_at = await self._session.scalar(select(func.max(StixObjectRow.ingested_at)))
        return {
            "total_objects": total_objects,
            "by_type": by_type,
            "last_ingested_at": last_ingested_at,
        }

    async def get_ingest_timeseries(self, *, days: int) -> dict[str, Any]:
        if days < 1:
            msg = "days must be >= 1"
            raise ValueError(msg)
        end_date = datetime.now(UTC).date()
        start_date = end_date - timedelta(days=days - 1)
        start_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=UTC)

        day_bucket = sa.cast(sa.func.timezone("UTC", StixObjectRow.ingested_at), Date)
        stmt = (
            select(day_bucket, StixObjectRow.type, func.count())
            .where(StixObjectRow.ingested_at >= start_dt)
            .where(StixObjectRow.type.in_(("indicator", "vulnerability")))
            .group_by(day_bucket, StixObjectRow.type)
        )
        result = await self._session.execute(stmt)
        counts: dict[tuple[date, str], int] = {}
        for bucket, stix_type, cnt in result.all():
            if isinstance(bucket, datetime):
                d = bucket.date()
            elif isinstance(bucket, date):
                d = bucket
            else:
                d = date.fromisoformat(str(bucket))
            counts[(d, str(stix_type))] = int(cnt)

        series: list[dict[str, Any]] = []
        cur = start_date
        while cur <= end_date:
            series.append(
                {
                    "date": cur.isoformat(),
                    "indicator": counts.get((cur, "indicator"), 0),
                    "vulnerability": counts.get((cur, "vulnerability"), 0),
                },
            )
            cur += timedelta(days=1)

        return {"days": days, "series": series}


class SqlAlchemyRelationshipRepository:
    """Load relationship SDOs from ``stix_objects``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_relationships(self, stix_id: str) -> list[dict[str, Any]]:
        src = StixObjectRow.raw["source_ref"].as_string()
        tgt = StixObjectRow.raw["target_ref"].as_string()
        stmt = (
            select(StixObjectRow)
            .where(
                StixObjectRow.type == "relationship",
                or_(src == stix_id, tgt == stix_id),
            )
            .order_by(StixObjectRow.ingested_at.desc())
        )
        rows = (await self._session.scalars(stmt)).all()
        return [_stix_row_to_public_dict(r) for r in rows]


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
