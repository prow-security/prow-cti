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

from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from prow.api.app import app
from prow.api.deps import get_supervisor
from prow.connector.supervisor_state import ConnectorState


@pytest.fixture
def mock_supervisor():
    supervisor = MagicMock()

    inst1 = MagicMock()
    inst1.instance_id = "kev-dev"
    inst1.entry_point_name = "cisa-kev"
    inst1.state = ConnectorState.RUNNING
    inst1.last_restart_at = None
    inst1.restart_attempts_in_window = 0

    supervisor.list_instances.return_value = [inst1]

    def get_instance(instance_id):
        if instance_id == "kev-dev":
            return inst1
        raise KeyError(instance_id)

    supervisor.get_instance.side_effect = get_instance
    return supervisor


@pytest.fixture
def client(mock_supervisor):
    async def override_get_supervisor():
        return mock_supervisor

    app.dependency_overrides[get_supervisor] = override_get_supervisor
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_list_connectors(client):
    response = await client.get("/api/v1/connectors")
    assert response.status_code == 200
    data = response.json()
    assert len(data["instances"]) == 1
    assert data["instances"][0]["instance_id"] == "kev-dev"
    assert data["instances"][0]["entry_point_name"] == "cisa-kev"
    assert data["instances"][0]["state"] == "running"


@pytest.mark.asyncio
async def test_get_connector(client):
    response = await client.get("/api/v1/connectors/kev-dev")
    assert response.status_code == 200
    data = response.json()
    assert data["instance_id"] == "kev-dev"
    assert data["entry_point_name"] == "cisa-kev"


@pytest.mark.asyncio
async def test_get_connector_not_found(client):
    response = await client.get("/api/v1/connectors/nonexistent")
    assert response.status_code == 404
    assert response.json() == {"detail": "Connector instance not found", "id": "nonexistent"}
