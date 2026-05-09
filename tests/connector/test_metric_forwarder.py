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

from datetime import UTC, datetime
from unittest.mock import MagicMock

from prow.connector.metric_forwarder import MetricForwarder
from prow.connector.protocol.messages import MetricPayload


def test_counter_observation_namespaced() -> None:
    meter = MagicMock()
    ctr = MagicMock()
    meter.create_counter.return_value = ctr
    mf = MetricForwarder("inst-a", "my_ep", meter)
    ts = datetime.now(UTC)
    mf.forward(
        MetricPayload(name="events.total", value=3.0, unit=None, tags={}, timestamp=ts),
    )
    meter.create_counter.assert_called_once_with("prow.connector.my_ep.events.total")
    ctr.add.assert_called_once()
    assert ctr.add.call_args[0][0] == 3.0


def test_same_metric_reuses_instrument() -> None:
    meter = MagicMock()
    ctr = MagicMock()
    meter.create_counter.return_value = ctr
    mf = MetricForwarder("i", "ep", meter)
    ts = datetime.now(UTC)
    mf.forward(MetricPayload(name="x", value=1.0, unit="count", tags={}, timestamp=ts))
    mf.forward(MetricPayload(name="x", value=2.0, unit="", tags={}, timestamp=ts))
    meter.create_counter.assert_called_once()
    assert ctr.add.call_count == 2


def test_meter_none_is_noop() -> None:
    mf = MetricForwarder("i", "ep", None)
    ts = datetime.now(UTC)
    mf.forward(MetricPayload(name="n", value=1.0, unit=None, tags={}, timestamp=ts))


def test_meter_raises_fail_soft() -> None:
    meter = MagicMock()
    meter.create_counter.side_effect = RuntimeError("otel broken")
    mf = MetricForwarder("i", "ep", meter)
    ts = datetime.now(UTC)
    mf.forward(MetricPayload(name="c", value=1.0, unit=None, tags={}, timestamp=ts))


def test_tag_conflict_standard_wins() -> None:
    meter = MagicMock()
    ctr = MagicMock()
    meter.create_counter.return_value = ctr
    mf = MetricForwarder("real-id", "real-ep", meter)
    ts = datetime.now(UTC)
    mf.forward(
        MetricPayload(
            name="m",
            value=1.0,
            unit="1",
            tags={"connector_instance_id": "wrong", "entry_point_name": "wrong"},
            timestamp=ts,
        ),
    )
    attrs = ctr.add.call_args[1]["attributes"]
    assert attrs == {
        "connector_instance_id": "real-id",
        "entry_point_name": "real-ep",
    }


def test_dot_in_metric_name_is_namespaced_not_bypass() -> None:
    meter = MagicMock()
    ctr = MagicMock()
    meter.create_counter.return_value = ctr
    mf = MetricForwarder("i", "entry", meter)
    ts = datetime.now(UTC)
    mf.forward(MetricPayload(name="foo.bar", value=1.0, unit="", tags={}, timestamp=ts))
    meter.create_counter.assert_called_once_with("prow.connector.entry.foo.bar")


def test_counter_vs_histogram_heuristic() -> None:
    meter = MagicMock()
    ctr = MagicMock()
    hist = MagicMock()
    meter.create_counter.return_value = ctr
    meter.create_histogram.return_value = hist
    mf = MetricForwarder("i", "ep", meter)
    ts = datetime.now(UTC)
    mf.forward(MetricPayload(name="c", value=2.0, unit="", tags={}, timestamp=ts))
    mf.forward(MetricPayload(name="h", value=0.5, unit="ms", tags={}, timestamp=ts))
    meter.create_counter.assert_called_once_with("prow.connector.ep.c")
    meter.create_histogram.assert_called_once_with("prow.connector.ep.h")
