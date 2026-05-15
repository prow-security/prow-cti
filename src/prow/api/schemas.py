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

"""Pydantic response schemas for the API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class StixObjectListResponse(BaseModel):
    objects: list[dict[str, Any]]
    total: int
    limit: int
    offset: int


class StixObjectResponse(BaseModel):
    object: dict[str, Any]


class RelationshipListResponse(BaseModel):
    relationships: list[dict[str, Any]]
    total: int


class SearchResponse(BaseModel):
    objects: list[dict[str, Any]]
    total: int


class ConnectorInstanceSummary(BaseModel):
    instance_id: str
    entry_point_name: str
    state: str
    last_restart_at: datetime | None
    restart_attempts_in_window: int


class ConnectorListResponse(BaseModel):
    instances: list[ConnectorInstanceSummary]


class IngestStats(BaseModel):
    total_objects: int
    by_type: dict[str, int]
    last_ingested_at: datetime | None


class HealthResponse(BaseModel):
    status: str
    version: str
    detail: str | None = None
