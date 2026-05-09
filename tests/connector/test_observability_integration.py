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
# WITHOUT WARRANTIES OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import asyncio
from typing import Any

import pytest
import structlog
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from structlog.testing import capture_logs

from prow.connector.protocol.messages import EmitAckPayload
from prow.connector.supervisor import Supervisor
from prow.connector.supervisor_state import ConnectorState


async def _wait_ready(inst: Any, *, timeout_s: float = 20.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        if inst.state == ConnectorState.READY:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"timeout waiting for READY, last state={inst.state!r}")


def _sum_counter_values(reader: InMemoryMetricReader, needle: str) -> float:
    total = 0.0
    data = reader.get_metrics_data()
    if data is None:
        return 0.0
    for rm in data.resource_metrics:
        for sm in rm.scope_metrics:
            for metric in sm.metrics:
                if needle not in metric.name:
                    continue
                # Counter instrument uses Sum aggregation (NumberDataPoint).
                for dp in metric.data.data_points:
                    total += float(dp.value)
    return total


@pytest.mark.slow
@pytest.mark.asyncio
async def test_logs_and_metrics_forwarded_with_identity() -> None:
    structlog.reset_defaults()

    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    meter = provider.get_meter("obs-integration-test")

    async def emit(_i: str, _b: dict[str, Any]) -> EmitAckPayload:
        return EmitAckPayload(accepted=0, duplicates=0, validation_failures=[])

    async def get_s(_i: str, _k: str) -> Any | None:
        return None

    async def set_s(_i: str, _k: str, _v: Any) -> None:
        return None

    with capture_logs() as cap:
        sup = Supervisor(
            "0.0.0",
            emit,
            get_s,
            set_s,
            health_probe_interval_seconds=None,
            meter=meter,
        )
        sup.add_instance("v", "verbose_logger_test", {"token": "a"})
        sup.add_instance("m", "metric_emitter_test", {"token": "b"})
        await sup.start_all()
        await _wait_ready(sup.get_instance("v"))
        await _wait_ready(sup.get_instance("m"))
        await sup.shutdown_all(25)

    verbose_events = [e for e in cap if e.get("event") == "verbose.record"]
    assert len(verbose_events) == 100
    assert all(e.get("connector_instance_id") == "v" for e in verbose_events)

    throughput_sum = _sum_counter_values(reader, "prow.connector.metric_emitter_test.throughput")
    assert throughput_sum == 50.0
