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

"""Dev-mode emit handler: STIX validation + human-readable summaries."""

from __future__ import annotations

import sys
from collections import Counter
from datetime import datetime
from typing import Any, TextIO

from prow.connector.protocol.messages import EmitAckPayload, ValidationFailure
from prow.stix import StixValidationError, validate_stix_object


class DevEmitHandler:
    """Emit handler for the dev runtime. Validates bundles via prow.stix.

    Prints a short summary to *stream* (stdout by default). Does not persist.
    """

    def __init__(
        self,
        stream: TextIO | None = None,
        *,
        allow_custom_types: bool = False,
    ) -> None:
        self._stream = stream or sys.stdout
        self._allow_custom_types = allow_custom_types

    async def __call__(self, _instance_id: str, bundle: dict[str, Any]) -> EmitAckPayload:
        bundle_id = bundle.get("id")
        if not isinstance(bundle_id, str):
            bundle_id = "?"

        if bundle.get("type") != "bundle":
            vf = ValidationFailure(
                object_id=bundle_id, error="emit payload must be a STIX bundle (type=bundle)"
            )
            self._print_line(bundle_id, 0, Counter(), [vf])
            return EmitAckPayload(accepted=0, duplicates=0, validation_failures=[vf])

        raw_objects = bundle.get("objects")
        if not isinstance(raw_objects, list):
            vf = ValidationFailure(object_id=bundle_id, error="bundle.objects must be a list")
            self._print_line(bundle_id, 0, Counter(), [vf])
            return EmitAckPayload(accepted=0, duplicates=0, validation_failures=[vf])

        type_counts: Counter[str] = Counter()
        failures: list[ValidationFailure] = []
        accepted = 0
        for obj in raw_objects:
            if not isinstance(obj, dict):
                oid = "?"
                failures.append(
                    ValidationFailure(
                        object_id=oid, error="bundle.objects entries must be objects"
                    ),
                )
                type_counts["?"] += 1
                continue
            t = obj.get("type")
            type_counts[str(t) if t is not None else "?"] += 1
            oid_raw = obj.get("id")
            oid = str(oid_raw) if oid_raw is not None else "?"
            try:
                validate_stix_object(obj, allow_custom_types=self._allow_custom_types)
            except StixValidationError as exc:
                failures.append(ValidationFailure(object_id=oid, error="; ".join(exc.errors)))
                continue
            accepted += 1

        self._print_line(bundle_id, len(raw_objects), type_counts, failures)
        return EmitAckPayload(
            accepted=accepted,
            duplicates=0,
            validation_failures=failures,
        )

    def _print_line(
        self,
        bundle_id: str,
        total_objects: int,
        type_counts: Counter[str],
        failures: list[ValidationFailure],
    ) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        failed = len(failures)
        typed = ", ".join(f"{n} {t}" for t, n in sorted(type_counts.items()))
        if not typed:
            typed = "0 types"
        line = (
            f"[{stamp}] emit: {total_objects} objects ({typed}; {failed} failed) "
            f"bundle={bundle_id}\n"
        )
        self._stream.write(line)
        self._stream.flush()
