# Copyright 2026 Prow Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Pure restart policy for connector instances."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from prow.connector.process import ProcessExitReason

RestartAction = Literal["restart", "circuit_break", "stop"]


@dataclass(frozen=True)
class RestartDecision:
    """Outcome of :meth:`RestartPolicy.should_restart`."""

    action: RestartAction
    delay_seconds: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class RestartPolicy:
    """Per-instance restart policy (defaults match the runtime design note)."""

    backoff_schedule_seconds: tuple[float, ...] = (1, 2, 4, 8, 30)
    backoff_ceiling_seconds: float = 30.0
    max_restarts_in_window: int = 3
    window_duration_seconds: float = 300.0
    restartable_exit_reasons: frozenset[ProcessExitReason] = field(
        default_factory=lambda: frozenset(
            {
                ProcessExitReason.CRASHED,
                ProcessExitReason.TIMEOUT_KILLED,
                ProcessExitReason.PROTOCOL_ERROR,
            },
        ),
    )

    def should_restart(
        self,
        exit_reason: ProcessExitReason,
        recent_restart_timestamps: list[datetime],
        *,
        now: datetime,
    ) -> RestartDecision:
        """Pure decision over exit reason and bounded rolling restart history."""

        if exit_reason not in self.restartable_exit_reasons:
            return RestartDecision(
                action="stop",
                reason=f"exit reason {exit_reason!s} is not restartable",
            )

        window_start = now - timedelta(seconds=self.window_duration_seconds)
        in_window = [t for t in recent_restart_timestamps if t >= window_start]
        if len(in_window) >= self.max_restarts_in_window:
            return RestartDecision(
                action="circuit_break",
                reason=(
                    f"{len(in_window)} restart events in "
                    f"{self.window_duration_seconds}s window (max "
                    f"{self.max_restarts_in_window})"
                ),
            )

        idx = max(len(in_window) - 1, 0)
        if idx < len(self.backoff_schedule_seconds):
            delay = float(self.backoff_schedule_seconds[idx])
        else:
            delay = float(self.backoff_ceiling_seconds)

        return RestartDecision(action="restart", delay_seconds=delay, reason="scheduled backoff")


def trim_restart_timestamps(
    timestamps: list[datetime],
    *,
    now: datetime,
    window_seconds: float,
) -> None:
    """Drop timestamps older than the rolling window (mutates *timestamps* in place)."""

    cutoff = now - timedelta(seconds=window_seconds)
    timestamps[:] = [t for t in timestamps if t >= cutoff]


def utc_now() -> datetime:
    """UTC wall-clock ``now`` for rolling restart windows."""

    return datetime.now(UTC)
