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

"""Convert connector protocol metric payloads into OpenTelemetry observations."""

from __future__ import annotations

import structlog
from opentelemetry.metrics import Counter, Histogram, Meter

from prow.connector.protocol.messages import MetricPayload

_FW_LOGGER = structlog.get_logger(__name__)

_COUNT_LIKE_UNITS = frozenset({"", "count", "1"})


def _is_counter_unit(unit: str | None) -> bool:
    if unit is None:
        return True
    normalized = unit.strip().lower()
    return normalized in _COUNT_LIKE_UNITS


class MetricForwarder:
    """Converts protocol MetricPayload messages into OpenTelemetry metric observations.

    Per-instance namespacing; fail-soft.
    """

    def __init__(
        self,
        connector_instance_id: str,
        entry_point_name: str,
        meter: Meter | None = None,
    ) -> None:
        self._connector_instance_id = connector_instance_id
        self._entry_point_name = entry_point_name
        self._meter = meter
        self._counters: dict[str, Counter] = {}
        self._histograms: dict[str, Histogram] = {}

    def _namespaced_name(self, payload: MetricPayload) -> str:
        return f"prow.connector.{self._entry_point_name}.{payload.name}"

    def _merged_attributes(self, payload: MetricPayload) -> dict[str, str]:
        tags = dict(payload.tags)
        tags["connector_instance_id"] = self._connector_instance_id
        tags["entry_point_name"] = self._entry_point_name
        return tags

    def forward(self, payload: MetricPayload) -> None:
        if self._meter is None:
            return
        name = self._namespaced_name(payload)
        try:
            attrs = self._merged_attributes(payload)
            if _is_counter_unit(payload.unit):
                counter = self._counters.get(name)
                if counter is None:
                    counter = self._meter.create_counter(name)
                    self._counters[name] = counter
                counter.add(float(payload.value), attributes=attrs)
            else:
                histogram = self._histograms.get(name)
                if histogram is None:
                    histogram = self._meter.create_histogram(name)
                    self._histograms[name] = histogram
                histogram.record(float(payload.value), attributes=attrs)
        except Exception as exc:
            _FW_LOGGER.warning(
                "connector.metric_forwarder.failed",
                metric_name=name,
                error=str(exc),
                exc_info=True,
            )
