# Copyright 2026 Prow Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
#
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Unit tests for :class:`prow.connector.restart_policy.RestartPolicy`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from prow.connector.process import ProcessExitReason
from prow.connector.restart_policy import RestartPolicy, trim_restart_timestamps


def test_empty_history_restarts_with_first_schedule_delay() -> None:
    policy = RestartPolicy()
    now = datetime.now(UTC)
    decision = policy.should_restart(
        ProcessExitReason.CRASHED,
        [now],
        now=now,
    )
    assert decision.action == "restart"
    assert decision.delay_seconds == 1.0


def test_second_failure_uses_second_schedule_slot() -> None:
    policy = RestartPolicy()
    now = datetime.now(UTC)
    decision = policy.should_restart(
        ProcessExitReason.CRASHED,
        [now - timedelta(seconds=1), now],
        now=now,
    )
    assert decision.action == "restart"
    assert decision.delay_seconds == 2.0


def test_three_events_in_window_trips_circuit() -> None:
    policy = RestartPolicy()
    now = datetime.now(UTC)
    stamps = [now - timedelta(seconds=10), now - timedelta(seconds=5), now]
    decision = policy.should_restart(ProcessExitReason.CRASHED, stamps, now=now)
    assert decision.action == "circuit_break"


def test_old_timestamps_outside_window_no_longer_count() -> None:
    policy = RestartPolicy(max_restarts_in_window=3, window_duration_seconds=300.0)
    now = datetime.now(UTC)
    old = now - timedelta(seconds=400)
    stamps = [old, now - timedelta(seconds=1), now]
    trim_restart_timestamps(stamps, now=now, window_seconds=policy.window_duration_seconds)
    assert len(stamps) == 2
    decision = policy.should_restart(ProcessExitReason.CRASHED, stamps, now=now)
    assert decision.action == "restart"
    assert decision.delay_seconds == 2.0


def test_non_restartable_always_stops() -> None:
    policy = RestartPolicy()
    now = datetime.now(UTC)
    decision = policy.should_restart(
        ProcessExitReason.HELLO_FAILED,
        [now, now, now],
        now=now,
    )
    assert decision.action == "stop"


def test_custom_schedule_delays() -> None:
    policy = RestartPolicy(
        backoff_schedule_seconds=(10.0, 20.0),
        backoff_ceiling_seconds=99.0,
        max_restarts_in_window=50,
    )
    now = datetime.now(UTC)
    d0 = policy.should_restart(ProcessExitReason.CRASHED, [now], now=now)
    assert d0.delay_seconds == 10.0
    d1 = policy.should_restart(
        ProcessExitReason.CRASHED,
        [now - timedelta(seconds=1), now],
        now=now,
    )
    assert d1.delay_seconds == 20.0
    many = [now - timedelta(seconds=i) for i in range(5)]
    dceil = policy.should_restart(ProcessExitReason.CRASHED, many, now=now)
    assert dceil.delay_seconds == 99.0
