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

"""Helpers for ``prow connector list|purge|run`` CLI commands."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from prow.config import load_config
from prow.config.schema import ConnectorInstanceConfig, ProwConfig
from prow.db.models import StixObjectRow
from prow.db.purge import count_objects_for_instances, purge_connector_instances
from prow.db.session import session_scope

if TYPE_CHECKING:
    from prow.connector.supervisor import Supervisor


def instances_for_connector_name(
    config: ProwConfig,
    name: str,
    *,
    instance_id: str | None = None,
) -> list[ConnectorInstanceConfig]:
    matches = [c for c in config.connectors if c.name == name]
    if instance_id is not None:
        return [c for c in matches if c.id == instance_id]
    if len(matches) <= 1:
        return matches
    default_id = f"{name}-0"
    by_default = [c for c in matches if c.id == default_id]
    return by_default if by_default else [matches[0]]


def resolve_instance_ids(
    config: ProwConfig,
    name: str,
    *,
    instance_id: str | None = None,
) -> list[str]:
    if instance_id is not None:
        instances = instances_for_connector_name(config, name, instance_id=instance_id)
    else:
        instances = [c for c in config.connectors if c.name == name]
    ids: list[str] = []
    for inst in instances:
        if inst.id is not None:
            ids.append(inst.id)
    return ids


def supervisor_state_label(
    supervisor: Supervisor | None,
    instance_id: str,
    *,
    enabled: bool,
) -> str:
    if not enabled:
        return "disabled"
    if supervisor is None:
        return "config-only"
    try:
        inst = supervisor.get_instance(instance_id)
    except KeyError:
        return "not-loaded"
    return inst.state.value


async def fetch_object_count(
    session_factory: async_sessionmaker[AsyncSession],
    instance_id: str,
) -> int:
    async with session_scope(session_factory) as session:
        stmt = (
            sa.select(sa.func.count())
            .select_from(StixObjectRow)
            .where(StixObjectRow.source_connector_instance_id == instance_id)
        )
        result = await session.execute(stmt)
        return int(result.scalar_one())


async def fetch_last_ingest(
    session_factory: async_sessionmaker[AsyncSession],
    instance_id: str,
) -> datetime | None:
    async with session_scope(session_factory) as session:
        stmt = sa.select(sa.func.max(StixObjectRow.ingested_at)).where(
            StixObjectRow.source_connector_instance_id == instance_id,
        )
        result = await session.execute(stmt)
        value = result.scalar_one_or_none()
        return value if isinstance(value, datetime) else None


def format_relative_time(when: datetime | None) -> str:
    if when is None:
        return "never"
    now = datetime.now(UTC)
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    delta = now - when.astimezone(UTC)
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def format_connector_list_table(
    rows: list[tuple[str, str, str, str, str]],
) -> str:
    headers = ("NAME", "ID", "STATE", "OBJECTS", "LAST RUN")
    col_widths = [len(h) for h in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            col_widths[idx] = max(col_widths[idx], len(cell))

    def fmt_row(cells: tuple[str, ...]) -> str:
        return "  ".join(cell.ljust(col_widths[idx]) for idx, cell in enumerate(cells))

    lines = [fmt_row(headers), fmt_row(tuple("-" * w for w in col_widths))]
    lines.extend(fmt_row(row) for row in rows)
    return "\n".join(lines)


async def build_list_rows(
    config: ProwConfig,
    session_factory: async_sessionmaker[AsyncSession],
    supervisor: Supervisor | None,
) -> list[tuple[str, str, str, str, str]]:
    rows: list[tuple[str, str, str, str, str]] = []
    for inst_cfg in config.connectors:
        instance_id = inst_cfg.id
        if instance_id is None:
            continue
        state = supervisor_state_label(supervisor, instance_id, enabled=inst_cfg.enabled)
        if inst_cfg.enabled:
            count = await fetch_object_count(session_factory, instance_id)
            objects = f"{count:,}"
            last_run = format_relative_time(
                await fetch_last_ingest(session_factory, instance_id),
            )
        else:
            objects = "—"
            last_run = "never"
        rows.append((inst_cfg.name, instance_id, state, objects, last_run))
    return rows


async def purge_connector_data(
    session_factory: async_sessionmaker[AsyncSession],
    instance_ids: list[str],
) -> int:
    async with session_scope(session_factory) as session:
        deleted = await purge_connector_instances(session, instance_ids)
        await session.commit()
        return deleted


async def count_before_purge(
    session_factory: async_sessionmaker[AsyncSession],
    instance_ids: list[str],
) -> int:
    async with session_scope(session_factory) as session:
        return await count_objects_for_instances(session, instance_ids)


def load_cli_config() -> ProwConfig:
    return load_config()
