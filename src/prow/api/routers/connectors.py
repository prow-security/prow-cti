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

"""Connector status endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse

from prow.api.deps import get_supervisor
from prow.api.schemas import ConnectorInstanceSummary, ConnectorListResponse
from prow.connector.supervisor import Supervisor

router = APIRouter(prefix="/api/v1")


@router.get("/connectors", response_model=ConnectorListResponse)
async def list_connectors(
    supervisor: Annotated[Supervisor, Depends(get_supervisor)],
) -> ConnectorListResponse:
    """List all connector instances."""
    instances = supervisor.list_instances()
    summaries = [
        ConnectorInstanceSummary(
            instance_id=inst.instance_id,
            entry_point_name=inst.entry_point_name,
            state=inst.state.value,
            last_restart_at=inst.last_restart_at,
            restart_attempts_in_window=inst.restart_attempts_in_window,
        )
        for inst in instances
    ]
    return ConnectorListResponse(instances=summaries)


@router.get("/connectors/{instance_id}", response_model=ConnectorInstanceSummary)
async def get_connector(
    instance_id: str,
    supervisor: Annotated[Supervisor, Depends(get_supervisor)],
) -> ConnectorInstanceSummary | Response:
    """Get a single connector instance."""
    try:
        inst = supervisor.get_instance(instance_id)
    except KeyError:
        return JSONResponse(
            status_code=404,
            content={"detail": "Connector instance not found", "id": instance_id},
        )

    return ConnectorInstanceSummary(
        instance_id=inst.instance_id,
        entry_point_name=inst.entry_point_name,
        state=inst.state.value,
        last_restart_at=inst.last_restart_at,
        restart_attempts_in_window=inst.restart_attempts_in_window,
    )
