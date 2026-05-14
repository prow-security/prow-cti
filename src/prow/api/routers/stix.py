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

"""STIX query endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse

from prow.api.deps import get_relationship_repo, get_stix_object_repo
from prow.api.schemas import (
    RelationshipListResponse,
    SearchResponse,
    StixObjectListResponse,
    StixObjectResponse,
)
from prow.db.repositories import RelationshipRepository, StixObjectRepository

router = APIRouter(prefix="/api/v1")


@router.get("/objects", response_model=StixObjectListResponse)
async def list_objects(
    repo: Annotated[StixObjectRepository, Depends(get_stix_object_repo)],
    type: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> StixObjectListResponse:
    """List STIX objects."""
    objects, total = await repo.list_objects(stix_type=type, limit=limit, offset=offset)
    return StixObjectListResponse(
        objects=objects,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/objects/{stix_id}", response_model=StixObjectResponse)
async def get_object(
    stix_id: str,
    repo: Annotated[StixObjectRepository, Depends(get_stix_object_repo)],
) -> StixObjectResponse | Response:
    """Get a single STIX object by ID."""
    obj = await repo.get_object(stix_id)
    if obj is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "Object not found", "id": stix_id},
        )
    return StixObjectResponse(object=obj)


@router.get("/search", response_model=SearchResponse)
async def search_objects(
    q: str,
    repo: Annotated[StixObjectRepository, Depends(get_stix_object_repo)],
    type: str | None = None,
    limit: int = Query(50, ge=1, le=200),
) -> SearchResponse:
    """Search for STIX objects."""
    # First try observable search
    objects, total = await repo.search_by_observable(q, stix_type=type, limit=limit)

    # If no results, fall back to full text search
    if total == 0:
        objects, total = await repo.full_text_search(q, stix_type=type, limit=limit)

    return SearchResponse(objects=objects, total=total)


@router.get("/objects/{stix_id}/relationships", response_model=RelationshipListResponse)
async def get_object_relationships(
    stix_id: str,
    stix_repo: Annotated[StixObjectRepository, Depends(get_stix_object_repo)],
    rel_repo: Annotated[RelationshipRepository, Depends(get_relationship_repo)],
) -> RelationshipListResponse | Response:
    """Get relationships for a STIX object."""
    # Check if object exists
    obj = await stix_repo.get_object(stix_id)
    if obj is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "Object not found", "id": stix_id},
        )

    relationships = await rel_repo.get_relationships(stix_id)
    return RelationshipListResponse(
        relationships=relationships,
        total=len(relationships),
    )
