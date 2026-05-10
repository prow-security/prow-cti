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

"""Connector SDK surface for authors (context, transports, typing helpers).

Imports are lazy so ``from prow.connector.runner import main`` does not pull
runtime/STIX bundles before the subprocess attaches protocol streams (stdout
must stay JSONL-only).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from prow.connector.base import ConnectorBase
    from prow.connector.context import ConnectorContext, EmitResult
    from prow.connector.instance import ConnectorInstance
    from prow.connector.log_forwarder import LogForwarder
    from prow.connector.metric_forwarder import MetricForwarder
    from prow.connector.process import ConnectorProcess, ConnectorProcessState, ProcessExitReason
    from prow.connector.restart_policy import RestartDecision, RestartPolicy
    from prow.connector.runtime_transport import ConnectorProcessExited, ConnectorRuntimeTransport
    from prow.connector.supervisor import Supervisor
    from prow.connector.supervisor_state import ConnectorState, InvalidStateTransitionError
    from prow.connector.transport import ConnectorTransport
    from prow.connector.transport_inprocess import InProcessTransport
    from prow.connector.transport_stdio import StdioTransport, TooManyInFlightError


def __getattr__(name: str) -> Any:
    """Load connector SDK symbols on demand (subprocess entry avoids eager imports)."""

    if name == "ConnectorBase":
        from prow.connector.base import ConnectorBase

        return ConnectorBase
    if name == "ConnectorContext":
        from prow.connector.context import ConnectorContext

        return ConnectorContext
    if name == "ConnectorProcess":
        from prow.connector.process import ConnectorProcess

        return ConnectorProcess
    if name == "ConnectorProcessExited":
        from prow.connector.runtime_transport import ConnectorProcessExited

        return ConnectorProcessExited
    if name == "ConnectorProcessState":
        from prow.connector.process import ConnectorProcessState

        return ConnectorProcessState
    if name == "ConnectorRuntimeTransport":
        from prow.connector.runtime_transport import ConnectorRuntimeTransport

        return ConnectorRuntimeTransport
    if name == "ConnectorTransport":
        from prow.connector.transport import ConnectorTransport

        return ConnectorTransport
    if name == "EmitResult":
        from prow.connector.context import EmitResult

        return EmitResult
    if name == "InProcessTransport":
        from prow.connector.transport_inprocess import InProcessTransport

        return InProcessTransport
    if name == "ProcessExitReason":
        from prow.connector.process import ProcessExitReason

        return ProcessExitReason
    if name == "StdioTransport":
        from prow.connector.transport_stdio import StdioTransport

        return StdioTransport
    if name == "TooManyInFlightError":
        from prow.connector.transport_stdio import TooManyInFlightError

        return TooManyInFlightError
    if name == "Supervisor":
        from prow.connector.supervisor import Supervisor

        return Supervisor
    if name == "ConnectorInstance":
        from prow.connector.instance import ConnectorInstance

        return ConnectorInstance
    if name == "ConnectorState":
        from prow.connector.supervisor_state import ConnectorState

        return ConnectorState
    if name == "InvalidStateTransitionError":
        from prow.connector.supervisor_state import InvalidStateTransitionError

        return InvalidStateTransitionError
    if name == "RestartPolicy":
        from prow.connector.restart_policy import RestartPolicy

        return RestartPolicy
    if name == "RestartDecision":
        from prow.connector.restart_policy import RestartDecision

        return RestartDecision
    if name == "LogForwarder":
        from prow.connector.log_forwarder import LogForwarder

        return LogForwarder
    if name == "MetricForwarder":
        from prow.connector.metric_forwarder import MetricForwarder

        return MetricForwarder
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


__all__ = [
    "ConnectorBase",
    "ConnectorContext",
    "ConnectorInstance",
    "ConnectorProcess",
    "ConnectorProcessExited",
    "ConnectorProcessState",
    "ConnectorRuntimeTransport",
    "ConnectorState",
    "ConnectorTransport",
    "EmitResult",
    "InProcessTransport",
    "InvalidStateTransitionError",
    "LogForwarder",
    "MetricForwarder",
    "ProcessExitReason",
    "RestartDecision",
    "RestartPolicy",
    "StdioTransport",
    "Supervisor",
    "TooManyInFlightError",
]
