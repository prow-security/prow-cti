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

"""Ingestion stats endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from prow.api.deps import get_stix_object_repo
from prow.api.schemas import IngestStats
from prow.db.repositories import StixObjectRepository

router = APIRouter(prefix="/api/v1")


@router.get("/ingest/stats", response_model=IngestStats)
async def get_ingest_stats(
    repo: Annotated[StixObjectRepository, Depends(get_stix_object_repo)],
) -> IngestStats:
    """Get ingestion statistics."""
    stats = await repo.get_ingest_stats()
    return IngestStats(**stats)
