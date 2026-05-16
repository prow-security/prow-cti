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

"""JSON Schema validation entry point for STIX 2.1 objects.

This module discovers the vendored OASIS JSON Schemas under
``_schemas/2.1/`` at import time, compiles one
:class:`jsonschema.Draft202012Validator` per STIX object type, and
exposes :func:`validate_stix_object` / :func:`validate_many` for
callers.

Performance posture: validators are compiled exactly once per
process. Schema discovery walks the on-disk tree once and never
touches the network. The 10 000-indicator / 5-second budget called out
in the design note is a Pass B concern; this module aims for "fast
enough that the import-time cost is invisible".

The vendored schemas use upstream's relative ``$ref`` paths
(``../common/core.json`` and the like). We feed every schema into a
:mod:`referencing` registry keyed by each schema's declared ``$id`` so
that ``Draft202012Validator`` can resolve those refs without hitting
the network.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from importlib import resources
from importlib.resources.abc import Traversable
from typing import Any, Final

import structlog
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

__all__ = [
    "StixValidationError",
    "validate_many",
    "validate_stix_object",
]

_log = structlog.get_logger(__name__)

# Common-directory schemas that ARE STIX object types in their own
# right (everything else under common/ is a shared definition consumed
# only via $ref).
_COMMON_OBJECT_TYPES: Final[frozenset[str]] = frozenset(
    {
        "bundle",
        "extension-definition",
        "language-content",
        "marking-definition",
    }
)

# Subdirectories under _schemas/2.1/ whose every file declares a
# distinct STIX object type. Files under common/ are filtered through
# _COMMON_OBJECT_TYPES instead.
_OBJECT_DIRS: Final[frozenset[str]] = frozenset({"sdos", "observables", "sros"})

# Compiled once; STIX IDs are ``<type>--<uuid>`` per the spec.
_STIX_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[\w.-]+--[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class StixValidationError(ValueError):
    """Raised when a STIX object fails OASIS JSON Schema validation.

    Attributes:
        errors: Human-readable error strings, one per
            :class:`jsonschema.exceptions.ValidationError` produced by
            the underlying validator. Always non-empty.
        source: The offending object as supplied by the caller. Kept
            on the exception so callers can log or re-emit it without
            re-parsing the input stream.
    """

    def __init__(self, errors: list[str], source: dict[str, Any]) -> None:
        if not errors:
            errors = ["unknown validation failure"]
        super().__init__(errors[0])
        self.errors: list[str] = errors
        self.source: dict[str, Any] = source

    def __str__(self) -> str:
        return "; ".join(self.errors)


def _iter_schema_files(root: Traversable) -> Iterable[tuple[str, str, dict[str, Any]]]:
    """Yield ``(subdir_name, stem, schema_dict)`` for every JSON file under ``root``.

    ``subdir_name`` is the immediate parent directory under
    ``2.1/`` (e.g. ``"sdos"``, ``"common"``); ``stem`` is the filename
    without ``.json``. The walker is deterministic in directory order
    so any future debug output stays diff-friendly.
    """
    for child in sorted(root.iterdir(), key=lambda p: p.name):
        if child.is_dir():
            for grandchild in sorted(child.iterdir(), key=lambda p: p.name):
                if grandchild.is_file() and grandchild.name.endswith(".json"):
                    raw = grandchild.read_text(encoding="utf-8")
                    schema = json.loads(raw)
                    stem = grandchild.name[: -len(".json")]
                    yield child.name, stem, schema


def _build_registry_and_validators() -> tuple[Registry[Any], dict[str, Draft202012Validator]]:
    """Discover schemas, build a referencing Registry, compile validators.

    Returns a tuple of:
        * the populated Registry (kept module-private; it lets the
          bundle helper recompile per-item validators only if Pass B
          ever needs to);
        * a mapping from STIX ``type`` field value to its compiled
          :class:`Draft202012Validator`.

    Failures here are programming errors, not user errors, and are
    surfaced as :class:`RuntimeError` so they show up loudly at import
    time rather than as opaque KeyErrors at first use.
    """
    schemas_root = resources.files("prow.stix") / "_schemas" / "2.1"
    registry: Registry[Any] = Registry()
    schemas_by_type: dict[str, dict[str, Any]] = {}
    discovered = 0

    for subdir, stem, schema in _iter_schema_files(schemas_root):
        discovered += 1

        schema_id = schema.get("$id")
        if not isinstance(schema_id, str) or not schema_id:
            raise RuntimeError(
                f"vendored schema {subdir}/{stem}.json is missing a string $id; "
                "registry resolution would be ambiguous"
            )

        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        registry = registry.with_resource(uri=schema_id, resource=resource)

        is_stix_type = subdir in _OBJECT_DIRS or (
            subdir == "common" and stem in _COMMON_OBJECT_TYPES
        )
        if is_stix_type:
            if stem in schemas_by_type:
                raise RuntimeError(
                    f"duplicate STIX type {stem!r} discovered while loading "
                    f"vendored schemas (second occurrence in {subdir}/)"
                )
            schemas_by_type[stem] = schema

    validators: dict[str, Draft202012Validator] = {
        stix_type: Draft202012Validator(schema, registry=registry)
        for stix_type, schema in schemas_by_type.items()
    }

    _log.debug(
        "stix.validators.compiled",
        schema_files_discovered=discovered,
        validator_count=len(validators),
    )
    return registry, validators


_REGISTRY, _VALIDATORS = _build_registry_and_validators()


def _format_error(err: ValidationError, *, prefix: str = "") -> str:
    """Render a :class:`ValidationError` as a single-line message.

    The JSON Pointer-like path tells the caller exactly where the
    offending value lives inside the original object.
    """
    path = "/".join(str(p) for p in err.absolute_path) or "<root>"
    location = f"{prefix}{path}" if prefix else path
    return f"{location}: {err.message}"


def _collect_errors(
    validator: Draft202012Validator, instance: dict[str, Any], *, prefix: str = ""
) -> list[str]:
    """Run a validator and collect every error as a formatted string."""
    return [_format_error(e, prefix=prefix) for e in validator.iter_errors(instance)]


def _resolve_validator(
    stix_type: object,
    source: dict[str, Any],
    *,
    allow_custom_types: bool,
) -> Draft202012Validator | None:
    """Look up the compiled validator for ``stix_type`` or raise / return None."""
    if not isinstance(stix_type, str) or not stix_type:
        raise StixValidationError(["object is missing a non-empty 'type' field"], source=source)
    validator = _VALIDATORS.get(stix_type)
    if validator is None:
        if allow_custom_types:
            return None
        raise StixValidationError([f"unknown STIX type {stix_type!r}"], source=source)
    return validator


def _validate_custom_type_minimal(obj: dict[str, Any]) -> list[str]:
    """Structural checks for STIX custom object types without vendored schemas."""
    errors: list[str] = []
    stix_type = obj.get("type")
    if not isinstance(stix_type, str) or not stix_type.strip():
        return ["object is missing a non-empty 'type' field"]

    obj_id = obj.get("id")
    if not isinstance(obj_id, str) or not obj_id.strip():
        errors.append("object is missing a non-empty 'id' field")
    elif not _STIX_ID_RE.match(obj_id):
        errors.append(f"id {obj_id!r} is not a valid STIX 2.1 identifier")
    elif not obj_id.startswith(f"{stix_type}--"):
        errors.append(f"id must begin with {stix_type!r} followed by '--'")

    spec = obj.get("spec_version")
    if spec is None:
        errors.append("spec_version must be '2.1'")
    elif spec != "2.1":
        errors.append("spec_version must be '2.1'")

    return errors


def _validate_custom_type_passthrough(obj: dict[str, Any]) -> None:
    """Accept a custom STIX type after minimal structural validation."""
    errors = _validate_custom_type_minimal(obj)
    if errors:
        raise StixValidationError(errors, source=obj)
    stix_type = obj["type"]
    obj_id = obj["id"]
    _log.debug(
        "stix.validator.custom_type_passthrough",
        stix_type=stix_type,
        object_id=obj_id,
    )


def _validate_bundle(obj: dict[str, Any], *, allow_custom_types: bool = False) -> None:
    """Validate a STIX bundle: structural checks, then per-item recursion.

    The bundle schema's ``$ref``-rich ``items`` clause already enforces
    per-object shape, but we still call :func:`validate_stix_object`
    on each entry so that ``StixValidationError.errors`` carries the
    exact index path. This duplicates a small amount of work but keeps
    the failure messages actionable for connector authors.
    """
    bundle_validator = _VALIDATORS["bundle"]
    bundle_errors = _collect_errors(bundle_validator, obj)

    sub_errors: list[str] = []
    raw_objects = obj.get("objects")
    if isinstance(raw_objects, list):
        for index, item in enumerate(raw_objects):
            if not isinstance(item, dict):
                sub_errors.append(f"objects/{index}: expected object, got {type(item).__name__}")
                continue
            try:
                validate_stix_object(item, allow_custom_types=allow_custom_types)
            except StixValidationError as exc:
                for msg in exc.errors:
                    sub_errors.append(f"objects/{index}/{msg}")

    all_errors = bundle_errors + sub_errors
    if all_errors:
        raise StixValidationError(all_errors, source=obj)


def validate_stix_object(
    obj: dict[str, Any],
    *,
    allow_custom_types: bool = False,
) -> None:
    """Validate a single STIX object against the vendored OASIS schemas.

    Args:
        obj: A pre-parsed STIX object as a plain ``dict``. Bundles
            are accepted and dispatched to :func:`_validate_bundle`,
            which validates the bundle structure and every contained
            object.

    Raises:
        StixValidationError: The object's ``type`` is missing,
            unknown, or the schema reports any structural or
            constraint violations. ``errors`` carries one entry per
            violation, prefixed with a JSON-Pointer-like path.
    """
    if not isinstance(obj, dict):
        raise StixValidationError(
            [f"expected dict, got {type(obj).__name__}"],
            source={"value": repr(obj)},
        )

    stix_type = obj.get("type")
    if stix_type == "bundle":
        _validate_bundle(obj, allow_custom_types=allow_custom_types)
        return

    validator = _resolve_validator(stix_type, obj, allow_custom_types=allow_custom_types)
    if validator is None:
        _validate_custom_type_passthrough(obj)
        return

    errors = _collect_errors(validator, obj)
    if errors:
        raise StixValidationError(errors, source=obj)


def validate_many(
    objects: Iterable[dict[str, Any]],
    *,
    allow_custom_types: bool = False,
) -> None:
    """Validate an iterable of STIX objects, reusing compiled validators.

    The first failure short-circuits — STIX ingestion is per-object
    transactional in the design, so callers want the first error fast
    rather than a deferred report at the end of a 10k-item batch.
    """
    for obj in objects:
        validate_stix_object(obj, allow_custom_types=allow_custom_types)
