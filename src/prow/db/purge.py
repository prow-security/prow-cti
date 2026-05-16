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

"""Delete all persisted data for one or more connector instances."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from prow.db.models import ConnectorStateRow, StixObjectRow


async def count_objects_for_instances(
    session: AsyncSession,
    instance_ids: Sequence[str],
) -> int:
    if not instance_ids:
        return 0
    stmt = (
        sa.select(sa.func.count())
        .select_from(StixObjectRow)
        .where(StixObjectRow.source_connector_instance_id.in_(instance_ids))
    )
    result = await session.execute(stmt)
    return int(result.scalar_one())


async def purge_connector_instances(
    session: AsyncSession,
    instance_ids: Sequence[str],
) -> int:
    """Delete STIX objects and connector state for the given instance IDs.

    Returns the number of ``stix_objects`` rows removed.
    """

    if not instance_ids:
        return 0

    await session.execute(
        sa.delete(ConnectorStateRow).where(
            ConnectorStateRow.connector_instance_id.in_(instance_ids),
        ),
    )
    result = await session.execute(
        sa.delete(StixObjectRow).where(
            StixObjectRow.source_connector_instance_id.in_(instance_ids),
        ),
    )
    rowcount = getattr(result, "rowcount", None)
    return int(rowcount) if rowcount is not None else 0
