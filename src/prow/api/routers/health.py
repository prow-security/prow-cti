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

"""Health check endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from prow.api.deps import get_db_session
from prow.api.schemas import HealthResponse

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse}},
)
async def health_check(
    response: Response,
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> HealthResponse:
    """Check API and database health."""
    try:
        await session.execute(text("SELECT 1"))
        return HealthResponse(status="ok", version="0.1.0")
    except Exception:
        response.status_code = 503
        return HealthResponse(
            status="degraded",
            version="0.1.0",
            detail="database unavailable",
        )
