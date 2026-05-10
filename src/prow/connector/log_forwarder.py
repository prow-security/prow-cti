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
# WITHOUT WARRANTIES OR ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Convert connector protocol log payloads into prow structlog records."""

from __future__ import annotations

import copy
from typing import Any

import structlog

from prow.connector.protocol.messages import LogPayload

_FW_LOGGER = structlog.get_logger(__name__)


def _redact_at_path(root: dict[str, Any], dotted_path: str) -> None:
    """Redact a leaf described by *dotted_path* (nested dict keys, not literal dots)."""

    parts = dotted_path.split(".")
    cur: Any = root
    for key in parts[:-1]:
        if not isinstance(cur, dict) or key not in cur:
            return
        cur = cur[key]
        if not isinstance(cur, dict):
            return
    leaf = parts[-1]
    if isinstance(cur, dict) and leaf in cur:
        cur[leaf] = "<redacted>"


class LogForwarder:
    """Converts protocol LogPayload messages into structured log records on prow's main logger.

    Per-instance bound context; secret redaction; fail-soft.
    """

    def __init__(
        self,
        connector_instance_id: str,
        entry_point_name: str,
        secret_field_paths: frozenset[str],
        *,
        logger: structlog.BoundLogger | None = None,
    ) -> None:
        base = logger if logger is not None else structlog.get_logger("prow.connector")
        self._logger = base.bind(
            connector_instance_id=connector_instance_id,
            entry_point_name=entry_point_name,
            connector=True,
        )
        self._secret_field_paths = secret_field_paths

    def forward(self, payload: LogPayload) -> None:
        try:
            fields = copy.deepcopy(dict(payload.fields))
            for path in self._secret_field_paths:
                _redact_at_path(fields, path)

            kwargs: dict[str, Any] = {**fields}
            kwargs["connector_timestamp"] = payload.timestamp.isoformat()
            if payload.exception is not None:
                kwargs["exc_info"] = payload.exception

            level_fn = getattr(self._logger, payload.level.value, self._logger.info)
            level_fn(payload.message, **kwargs)
        except Exception as exc:
            _FW_LOGGER.warning(
                "connector.log_forwarder.failed",
                payload_type=type(payload).__name__,
                error=str(exc),
                exc_info=True,
            )
