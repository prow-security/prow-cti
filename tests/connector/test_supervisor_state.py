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

"""Unit tests for the canonical supervisor transition table."""

from __future__ import annotations

import pytest

from prow.connector.supervisor_state import (
    SUPERVISOR_TRANSITION_TABLE,
    ConnectorState,
    InvalidStateTransitionError,
    SupervisorTransitionEvent,
    apply_transition,
)


def test_transition_table_has_expected_number_of_rows() -> None:
    assert len(SUPERVISOR_TRANSITION_TABLE) == 20


def test_every_non_terminal_state_has_an_outgoing_transition() -> None:
    sources = {s for (s, _e) in SUPERVISOR_TRANSITION_TABLE}
    terminal = {ConnectorState.DEAD}
    for st in ConnectorState:
        if st in terminal:
            continue
        assert st in sources, f"state {st!s} has no outgoing transition"


def test_invalid_transition_raises() -> None:
    with pytest.raises(InvalidStateTransitionError):
        apply_transition(ConnectorState.RUNNING, SupervisorTransitionEvent.HELLO_SUCCEEDED)


def test_representative_paths_use_only_table_transitions() -> None:
    s = ConnectorState.NOT_STARTED
    s = apply_transition(s, SupervisorTransitionEvent.START_INVOKED)
    assert s == ConnectorState.STARTING
    s = apply_transition(s, SupervisorTransitionEvent.HELLO_SUCCEEDED)
    assert s == ConnectorState.READY
    s = apply_transition(s, SupervisorTransitionEvent.FIRST_OPERATIONAL_MESSAGE)
    assert s == ConnectorState.RUNNING
    s = apply_transition(s, SupervisorTransitionEvent.SHUTDOWN_REQUESTED)
    assert s == ConnectorState.DRAINING
    s = apply_transition(s, SupervisorTransitionEvent.GRACEFUL_PROCESS_EXIT)
    assert s == ConnectorState.DEAD


def test_restart_and_circuit_path() -> None:
    s = apply_transition(ConnectorState.NOT_STARTED, SupervisorTransitionEvent.START_INVOKED)
    s = apply_transition(s, SupervisorTransitionEvent.START_FAILURE_TO_CRASHED)
    assert s == ConnectorState.CRASHED
    s = apply_transition(s, SupervisorTransitionEvent.RESTART_BACKOFF_ELAPSED)
    assert s == ConnectorState.STARTING
    s = ConnectorState.CRASHED
    s = apply_transition(s, SupervisorTransitionEvent.CIRCUIT_BREAK_RECORDED)
    assert s == ConnectorState.CIRCUIT_BROKEN
    s = apply_transition(s, SupervisorTransitionEvent.CIRCUIT_CLEAR_RESTART)
    assert s == ConnectorState.STARTING
