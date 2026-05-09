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

"""Canonical supervisor state machine for one connector instance."""

from __future__ import annotations

from enum import StrEnum


class ConnectorState(StrEnum):
    """Supervisor-facing lifecycle (runtime design note + implicit entry state)."""

    NOT_STARTED = "not_started"
    STARTING = "starting"
    READY = "ready"
    RUNNING = "running"
    DRAINING = "draining"
    DEAD = "dead"
    CRASHED = "crashed"
    CIRCUIT_BROKEN = "circuit_broken"


class SupervisorTransitionEvent(StrEnum):
    """Named transitions — table keys together with :class:`ConnectorState`."""

    START_INVOKED = "start_invoked"
    HELLO_SUCCEEDED = "hello_succeeded"
    START_FAILURE_TO_CRASHED = "start_failure_to_crashed"
    FIRST_OPERATIONAL_MESSAGE = "first_operational_message"
    SHUTDOWN_REQUESTED = "shutdown_requested"
    GRACEFUL_PROCESS_EXIT = "graceful_process_exit"
    GRACEFUL_EXIT_WITHOUT_DRAIN = "graceful_exit_without_drain"
    CRASH_WHILE_DRAINING = "crash_while_draining"
    CRASH_WHILE_ACTIVE = "crash_while_active"
    RESTART_BACKOFF_ELAPSED = "restart_backoff_elapsed"
    CIRCUIT_BREAK_RECORDED = "circuit_break_recorded"
    POLICY_STOP_TO_DEAD = "policy_stop_to_dead"
    CIRCUIT_CLEAR_RESTART = "circuit_clear_restart"
    RESTART_ABORT_TO_DEAD = "restart_abort_to_dead"


class InvalidStateTransitionError(Exception):
    """Raised when :func:`apply_transition` receives an undefined (*state*, *event*) pair."""


# Canonical transition table: (current_state, event) -> next_state.
SUPERVISOR_TRANSITION_TABLE: dict[
    tuple[ConnectorState, SupervisorTransitionEvent], ConnectorState
] = {
    (ConnectorState.NOT_STARTED, SupervisorTransitionEvent.START_INVOKED): ConnectorState.STARTING,
    (ConnectorState.DEAD, SupervisorTransitionEvent.START_INVOKED): ConnectorState.STARTING,
    (ConnectorState.STARTING, SupervisorTransitionEvent.HELLO_SUCCEEDED): ConnectorState.READY,
    (
        ConnectorState.STARTING,
        SupervisorTransitionEvent.START_FAILURE_TO_CRASHED,
    ): ConnectorState.CRASHED,
    (
        ConnectorState.STARTING,
        SupervisorTransitionEvent.SHUTDOWN_REQUESTED,
    ): ConnectorState.DRAINING,
    (
        ConnectorState.READY,
        SupervisorTransitionEvent.FIRST_OPERATIONAL_MESSAGE,
    ): ConnectorState.RUNNING,
    (ConnectorState.READY, SupervisorTransitionEvent.SHUTDOWN_REQUESTED): ConnectorState.DRAINING,
    (ConnectorState.RUNNING, SupervisorTransitionEvent.SHUTDOWN_REQUESTED): ConnectorState.DRAINING,
    (
        ConnectorState.READY,
        SupervisorTransitionEvent.GRACEFUL_EXIT_WITHOUT_DRAIN,
    ): ConnectorState.DEAD,
    (
        ConnectorState.RUNNING,
        SupervisorTransitionEvent.GRACEFUL_EXIT_WITHOUT_DRAIN,
    ): ConnectorState.DEAD,
    (ConnectorState.READY, SupervisorTransitionEvent.CRASH_WHILE_ACTIVE): ConnectorState.CRASHED,
    (ConnectorState.RUNNING, SupervisorTransitionEvent.CRASH_WHILE_ACTIVE): ConnectorState.CRASHED,
    (ConnectorState.DRAINING, SupervisorTransitionEvent.GRACEFUL_PROCESS_EXIT): ConnectorState.DEAD,
    (
        ConnectorState.DRAINING,
        SupervisorTransitionEvent.CRASH_WHILE_DRAINING,
    ): ConnectorState.CRASHED,
    (
        ConnectorState.CRASHED,
        SupervisorTransitionEvent.RESTART_BACKOFF_ELAPSED,
    ): ConnectorState.STARTING,
    (
        ConnectorState.CRASHED,
        SupervisorTransitionEvent.CIRCUIT_BREAK_RECORDED,
    ): ConnectorState.CIRCUIT_BROKEN,
    (ConnectorState.CRASHED, SupervisorTransitionEvent.POLICY_STOP_TO_DEAD): ConnectorState.DEAD,
    (ConnectorState.CRASHED, SupervisorTransitionEvent.RESTART_ABORT_TO_DEAD): ConnectorState.DEAD,
    (
        ConnectorState.CIRCUIT_BROKEN,
        SupervisorTransitionEvent.CIRCUIT_CLEAR_RESTART,
    ): ConnectorState.STARTING,
    (
        ConnectorState.CIRCUIT_BROKEN,
        SupervisorTransitionEvent.SHUTDOWN_REQUESTED,
    ): ConnectorState.DEAD,
}


def apply_transition(
    current: ConnectorState,
    event: SupervisorTransitionEvent,
) -> ConnectorState:
    """Return the successor state; invalid pairs raise :class:`InvalidStateTransitionError`."""

    key = (current, event)
    try:
        return SUPERVISOR_TRANSITION_TABLE[key]
    except KeyError as exc:
        msg = f"Invalid transition {current!s} + {event!s}"
        raise InvalidStateTransitionError(msg) from exc
