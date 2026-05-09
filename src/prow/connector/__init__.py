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
    from prow.connector.process import ConnectorProcess, ConnectorProcessState, ProcessExitReason
    from prow.connector.runtime_transport import ConnectorProcessExited, ConnectorRuntimeTransport
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
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


__all__ = [
    "ConnectorBase",
    "ConnectorContext",
    "ConnectorProcess",
    "ConnectorProcessExited",
    "ConnectorProcessState",
    "ConnectorRuntimeTransport",
    "ConnectorTransport",
    "EmitResult",
    "InProcessTransport",
    "ProcessExitReason",
    "StdioTransport",
    "TooManyInFlightError",
]
