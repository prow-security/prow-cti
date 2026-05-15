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

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from prow.api.app import app
from prow.api.deps import get_db_session


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.execute = AsyncMock()
    return session


@pytest.fixture
def client(mock_session):
    async def override_get_db_session():
        yield mock_session

    app.dependency_overrides[get_db_session] = override_get_db_session
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_health_ok(client, mock_session):
    mock_session.execute.return_value = None
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0", "detail": None}


@pytest.mark.asyncio
async def test_health_degraded(client, mock_session):
    mock_session.execute.side_effect = Exception("DB error")
    response = await client.get("/health")
    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "version": "0.1.0",
        "detail": "database unavailable",
    }


@pytest.mark.asyncio
async def test_openapi_docs(client):
    response = await client.get("/docs")
    assert response.status_code == 200
