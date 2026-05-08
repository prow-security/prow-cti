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

"""Prow-owned Pydantic v2 boundary types for STIX 2.1.

These models are the **only** way external code talks STIX inside
prow. The upstream :mod:`stix2` package is reachable from one place
(:mod:`prow.stix._stix2_adapter`); everything else — connectors, the
ingest pipeline, the API layer, the persister — speaks the types in
this module.

Scope is the v0.1 connector set per the design note's
"v0.1 STIX type scope": CISA KEV plus URLhaus / MITRE ATT&CK / MISP.
Adding a new STIX type is a localised change here plus a small one in
:mod:`prow.stix.helpers`; no other module needs to know.

Two parsing entry points exist on every model via the shared
:class:`_StixCommon` mixin:

* :meth:`_StixCommon.model_validate` — Pydantic-only structural check
  for prow-internal callers (connector authors, etc.).
* :meth:`_StixCommon.parse_external` — JSON Schema validation
  (vendored OASIS schemas) **then** Pydantic construction. Use this
  for any data crossing the trust boundary (third-party feeds, TAXII
  pulls, user uploads).

Custom STIX extension properties (the ``x_*`` prefix per the spec)
round-trip through the ``extensions`` dict on every model. A
``model_validator(mode="before")`` lifts them into the dict at parse
time; a ``model_serializer(mode="wrap")`` flattens the ``x_*`` keys
back to top level on dump while leaving extension-definition-keyed
entries nested under ``extensions`` (where the spec puts them). This
is the convention the design note's 2026-05-07 amendment commits to.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, ClassVar, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    field_serializer,
    model_serializer,
    model_validator,
)

from prow.stix._validate import validate_stix_object

__all__ = [
    "AttackPattern",
    "Bundle",
    "Campaign",
    "DomainName",
    "EmailAddr",
    "ExternalReference",
    "File",
    "GranularMarking",
    "Identity",
    "Indicator",
    "IntrusionSet",
    "Ipv4Addr",
    "Ipv6Addr",
    "KillChainPhase",
    "Malware",
    "MarkingDefinition",
    "ObservedData",
    "Relationship",
    "Report",
    "Sighting",
    "Software",
    "ThreatActor",
    "Tool",
    "Url",
    "Vulnerability",
]


# ---------------------------------------------------------------------------
# Datetime: STIX uses ISO 8601 with millisecond precision and a literal "Z"
# (e.g. "2026-05-07T19:19:22.123Z"). Pydantic's default serialiser does not
# guarantee that exact form, so we apply a shared field_serializer.
# ---------------------------------------------------------------------------


def _serialise_stix_timestamp(value: datetime) -> str:
    """Render ``value`` as a STIX-compliant ISO 8601 millisecond UTC string.

    Examples accepted by the spec:

    * ``"2026-05-07T19:19:22.000Z"`` (canonical)
    * ``"2026-05-07T19:19:22.123Z"``

    The spec mandates the trailing literal ``Z`` and the
    ``YYYY-MM-DDThh:mm:ss.sss`` fractional-seconds shape with at
    least three digits. We always emit exactly three (millisecond
    precision) so the output is byte-stable across runs.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    else:
        value = value.astimezone(UTC)
    millis = value.microsecond // 1000
    return value.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


# ---------------------------------------------------------------------------
# Common mixin: extension handling + JSON Schema entry point.
# ---------------------------------------------------------------------------


class _StixCommon(BaseModel):
    """Shared base for every STIX object the wrapper models.

    Carries the cross-cutting behaviour: extra-key tolerance, the
    ``x_*`` lifting/flattening logic, the timestamp serialiser
    binding (subclasses with datetime fields apply it), and the
    :meth:`parse_external` JSON-Schema entry point.
    """

    model_config = ConfigDict(
        extra="allow",
        populate_by_name=True,
        ser_json_timedelta="iso8601",
    )

    extensions: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _gather_custom_properties(cls, data: Any) -> Any:
        """Lift unknown ``x_*`` keys from the top level into ``extensions``.

        Spec ``extensions`` entries (extension-definition--… keys) are
        already nested correctly by upstream producers and pass
        through untouched.
        """
        if not isinstance(data, dict):
            return data
        existing_extensions = dict(data.get("extensions") or {})
        custom_keys = [k for k in list(data.keys()) if isinstance(k, str) and k.startswith("x_")]
        for key in custom_keys:
            existing_extensions[key] = data.pop(key)
        if existing_extensions:
            data["extensions"] = existing_extensions
        return data

    @model_serializer(mode="wrap")
    def _flatten_custom_properties(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """Dump the model, then re-flatten ``x_*`` keys back to top level.

        The result is STIX-on-the-wire shape: custom keys at the top,
        spec ``extensions`` entries (extension-definition--…) staying
        nested under ``extensions``. Empty values (``None``, empty
        list, empty dict) are dropped — STIX semantics treat
        omission and ``null`` as equivalent and most consumers reject
        explicit nulls.
        """
        raw: dict[str, Any] = handler(self)

        cleaned: dict[str, Any] = {
            key: value
            for key, value in raw.items()
            if value is not None and value != [] and value != {}
        }

        nested_extensions = cleaned.pop("extensions", None) or {}
        custom: dict[str, Any] = {}
        spec_extensions: dict[str, Any] = {}
        for key, value in nested_extensions.items():
            if isinstance(key, str) and key.startswith("x_"):
                custom[key] = value
            else:
                spec_extensions[key] = value

        cleaned.update(custom)
        if spec_extensions:
            cleaned["extensions"] = spec_extensions
        return cleaned

    @classmethod
    def parse_external(cls, data: dict[str, Any]) -> Self:
        """Validate ``data`` against the OASIS JSON schemas, then construct.

        This is the entry point for STIX coming from anywhere
        outside prow's trust boundary — TAXII pulls, third-party
        feeds, user uploads, replay fixtures. The JSON Schema check
        runs first because it gives a richer "where in the tree did
        this fail" message than Pydantic alone; Pydantic then
        narrows union members and parses datetimes.

        Args:
            data: A pre-parsed STIX object as a Python ``dict``.

        Returns:
            A validated instance of ``cls``.

        Raises:
            prow.stix._validate.StixValidationError: JSON Schema
                rejected the object.
            pydantic.ValidationError: Pydantic rejected the object
                after schema acceptance — usually a sign of a type
                we don't model fully, or the wrapper drifting from
                the spec.
        """
        validate_stix_object(data)
        return cls.model_validate(data)


# ---------------------------------------------------------------------------
# Common nested types referenced by SDOs / SROs / SMOs.
# ---------------------------------------------------------------------------


class ExternalReference(BaseModel):
    """A reference to a non-STIX information source."""

    model_config = ConfigDict(extra="allow")

    source_name: str
    description: str | None = None
    url: str | None = None
    hashes: dict[str, str] | None = None
    external_id: str | None = None


class KillChainPhase(BaseModel):
    """A single kill-chain phase referenced by an SDO."""

    model_config = ConfigDict(extra="allow")

    kill_chain_name: str
    phase_name: str


class GranularMarking(BaseModel):
    """A granular marking applying to specific fields of an object."""

    model_config = ConfigDict(extra="allow")

    selectors: list[str]
    marking_ref: str | None = None
    lang: str | None = None


# ---------------------------------------------------------------------------
# Per-category bases that carry the spec-common required/optional fields so
# specific types stay focused on their distinguishing properties.
# ---------------------------------------------------------------------------


class _StixDomainObject(_StixCommon):
    """Shared fields for every STIX Domain Object (and SRO)."""

    spec_version: Literal["2.1"] = "2.1"
    id: str
    created: datetime
    modified: datetime
    created_by_ref: str | None = None
    revoked: bool | None = None
    labels: list[str] | None = None
    confidence: int | None = Field(default=None, ge=0, le=100)
    lang: str | None = None
    external_references: list[ExternalReference] | None = None
    object_marking_refs: list[str] | None = None
    granular_markings: list[GranularMarking] | None = None

    @field_serializer("created", "modified", when_used="always")
    def _serialise_timestamps(self, value: datetime) -> str:
        return _serialise_stix_timestamp(value)


class _StixCyberObservable(_StixCommon):
    """Shared fields for every STIX Cyber-observable Object.

    SCOs intentionally lack ``created``/``modified``/``created_by_ref``;
    they identify content, not a moment in time.
    """

    spec_version: Literal["2.1"] = "2.1"
    id: str
    object_marking_refs: list[str] | None = None
    granular_markings: list[GranularMarking] | None = None
    defanged: bool | None = None


# ---------------------------------------------------------------------------
# SDOs — v0.1 connector scope.
# ---------------------------------------------------------------------------


class Indicator(_StixDomainObject):
    """STIX Indicator SDO (``type = "indicator"``)."""

    type: Literal["indicator"] = "indicator"
    pattern: str
    pattern_type: str
    pattern_version: str | None = None
    valid_from: datetime
    valid_until: datetime | None = None
    name: str | None = None
    description: str | None = None
    indicator_types: list[str] | None = None
    kill_chain_phases: list[KillChainPhase] | None = None

    @field_serializer("valid_from", "valid_until", when_used="unless-none")
    def _serialise_validity(self, value: datetime) -> str:
        return _serialise_stix_timestamp(value)


class Vulnerability(_StixDomainObject):
    """STIX Vulnerability SDO."""

    type: Literal["vulnerability"] = "vulnerability"
    name: str | None = None
    description: str | None = None


class Malware(_StixDomainObject):
    """STIX Malware SDO."""

    type: Literal["malware"] = "malware"
    is_family: bool
    name: str | None = None
    description: str | None = None
    malware_types: list[str] | None = None
    aliases: list[str] | None = None
    kill_chain_phases: list[KillChainPhase] | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    operating_system_refs: list[str] | None = None
    architecture_execution_envs: list[str] | None = None
    implementation_languages: list[str] | None = None
    capabilities: list[str] | None = None
    sample_refs: list[str] | None = None

    @field_serializer("first_seen", "last_seen", when_used="unless-none")
    def _serialise_seen(self, value: datetime) -> str:
        return _serialise_stix_timestamp(value)


class AttackPattern(_StixDomainObject):
    """STIX Attack Pattern SDO."""

    type: Literal["attack-pattern"] = "attack-pattern"
    name: str | None = None
    description: str | None = None
    aliases: list[str] | None = None
    kill_chain_phases: list[KillChainPhase] | None = None


class IntrusionSet(_StixDomainObject):
    """STIX Intrusion Set SDO."""

    type: Literal["intrusion-set"] = "intrusion-set"
    name: str | None = None
    description: str | None = None
    aliases: list[str] | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    goals: list[str] | None = None
    resource_level: str | None = None
    primary_motivation: str | None = None
    secondary_motivations: list[str] | None = None

    @field_serializer("first_seen", "last_seen", when_used="unless-none")
    def _serialise_seen(self, value: datetime) -> str:
        return _serialise_stix_timestamp(value)


class Tool(_StixDomainObject):
    """STIX Tool SDO."""

    type: Literal["tool"] = "tool"
    name: str | None = None
    description: str | None = None
    tool_types: list[str] | None = None
    aliases: list[str] | None = None
    kill_chain_phases: list[KillChainPhase] | None = None
    tool_version: str | None = None


class Campaign(_StixDomainObject):
    """STIX Campaign SDO."""

    type: Literal["campaign"] = "campaign"
    name: str | None = None
    description: str | None = None
    aliases: list[str] | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    objective: str | None = None

    @field_serializer("first_seen", "last_seen", when_used="unless-none")
    def _serialise_seen(self, value: datetime) -> str:
        return _serialise_stix_timestamp(value)


class ThreatActor(_StixDomainObject):
    """STIX Threat Actor SDO."""

    type: Literal["threat-actor"] = "threat-actor"
    name: str | None = None
    description: str | None = None
    threat_actor_types: list[str] | None = None
    aliases: list[str] | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    roles: list[str] | None = None
    goals: list[str] | None = None
    sophistication: str | None = None
    resource_level: str | None = None
    primary_motivation: str | None = None
    secondary_motivations: list[str] | None = None
    personal_motivations: list[str] | None = None

    @field_serializer("first_seen", "last_seen", when_used="unless-none")
    def _serialise_seen(self, value: datetime) -> str:
        return _serialise_stix_timestamp(value)


class Identity(_StixDomainObject):
    """STIX Identity SDO."""

    type: Literal["identity"] = "identity"
    name: str
    description: str | None = None
    roles: list[str] | None = None
    identity_class: str | None = None
    sectors: list[str] | None = None
    contact_information: str | None = None


class Report(_StixDomainObject):
    """STIX Report SDO."""

    type: Literal["report"] = "report"
    name: str
    description: str | None = None
    report_types: list[str] | None = None
    published: datetime
    object_refs: list[str]

    @field_serializer("published", when_used="always")
    def _serialise_published(self, value: datetime) -> str:
        return _serialise_stix_timestamp(value)


class ObservedData(_StixDomainObject):
    """STIX Observed Data SDO."""

    type: Literal["observed-data"] = "observed-data"
    first_observed: datetime
    last_observed: datetime
    number_observed: int = Field(ge=1)
    object_refs: list[str] | None = None
    objects: dict[str, Any] | None = None

    @field_serializer("first_observed", "last_observed", when_used="always")
    def _serialise_observed(self, value: datetime) -> str:
        return _serialise_stix_timestamp(value)


class Software(_StixDomainObject):
    """STIX Software SDO.

    Note: STIX 2.1 also defines a ``software`` SCO with a different
    field set; the SDO form is what the v0.1 connector list (CISA
    KEV vendor/product naming) consumes.
    """

    type: Literal["software"] = "software"
    name: str
    cpe: str | None = None
    swid: str | None = None
    languages: list[str] | None = None
    vendor: str | None = None
    version: str | None = None


# ---------------------------------------------------------------------------
# SCOs — v0.1 connector scope.
# ---------------------------------------------------------------------------


class Ipv4Addr(_StixCyberObservable):
    """STIX IPv4 Address SCO."""

    type: Literal["ipv4-addr"] = "ipv4-addr"
    value: str
    resolves_to_refs: list[str] | None = None
    belongs_to_refs: list[str] | None = None

    ID_CONTRIBUTING_PROPERTIES: ClassVar[tuple[str, ...]] = ("value",)


class Ipv6Addr(_StixCyberObservable):
    """STIX IPv6 Address SCO."""

    type: Literal["ipv6-addr"] = "ipv6-addr"
    value: str
    resolves_to_refs: list[str] | None = None
    belongs_to_refs: list[str] | None = None

    ID_CONTRIBUTING_PROPERTIES: ClassVar[tuple[str, ...]] = ("value",)


class DomainName(_StixCyberObservable):
    """STIX Domain Name SCO."""

    type: Literal["domain-name"] = "domain-name"
    value: str
    resolves_to_refs: list[str] | None = None

    ID_CONTRIBUTING_PROPERTIES: ClassVar[tuple[str, ...]] = ("value",)


class Url(_StixCyberObservable):
    """STIX URL SCO."""

    type: Literal["url"] = "url"
    value: str

    ID_CONTRIBUTING_PROPERTIES: ClassVar[tuple[str, ...]] = ("value",)


class File(_StixCyberObservable):
    """STIX File SCO."""

    type: Literal["file"] = "file"
    name: str | None = None
    size: int | None = Field(default=None, ge=0)
    hashes: dict[str, str] | None = None
    name_enc: str | None = None
    magic_number_hex: str | None = None
    mime_type: str | None = None
    ctime: datetime | None = None
    mtime: datetime | None = None
    atime: datetime | None = None
    parent_directory_ref: str | None = None
    contains_refs: list[str] | None = None
    content_ref: str | None = None

    ID_CONTRIBUTING_PROPERTIES: ClassVar[tuple[str, ...]] = ("hashes", "name", "extensions")

    @field_serializer("ctime", "mtime", "atime", when_used="unless-none")
    def _serialise_file_times(self, value: datetime) -> str:
        return _serialise_stix_timestamp(value)


class EmailAddr(_StixCyberObservable):
    """STIX Email Address SCO."""

    type: Literal["email-addr"] = "email-addr"
    value: str
    display_name: str | None = None
    belongs_to_ref: str | None = None

    ID_CONTRIBUTING_PROPERTIES: ClassVar[tuple[str, ...]] = ("value",)


# ---------------------------------------------------------------------------
# SROs.
# ---------------------------------------------------------------------------


class Relationship(_StixDomainObject):
    """STIX Relationship SRO — the directed edge between two STIX objects."""

    type: Literal["relationship"] = "relationship"
    relationship_type: str
    source_ref: str
    target_ref: str
    description: str | None = None
    start_time: datetime | None = None
    stop_time: datetime | None = None

    @field_serializer("start_time", "stop_time", when_used="unless-none")
    def _serialise_window(self, value: datetime) -> str:
        return _serialise_stix_timestamp(value)


class Sighting(_StixDomainObject):
    """STIX Sighting SRO — records that a SDO was observed."""

    type: Literal["sighting"] = "sighting"
    sighting_of_ref: str
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    count: int | None = Field(default=None, ge=0)
    observed_data_refs: list[str] | None = None
    where_sighted_refs: list[str] | None = None
    summary: bool | None = None
    description: str | None = None

    @field_serializer("first_seen", "last_seen", when_used="unless-none")
    def _serialise_seen(self, value: datetime) -> str:
        return _serialise_stix_timestamp(value)


# ---------------------------------------------------------------------------
# SMOs.
# ---------------------------------------------------------------------------


class MarkingDefinition(_StixCommon):
    """STIX Marking Definition SMO.

    The spec's marking-definition has a ``oneOf`` shape: one branch
    requires ``definition_type`` + ``definition`` for legacy
    statement / TLP-1.0 markings; another branch lets new markings
    (TLP 2.0 included) live entirely inside the ``extensions`` map
    keyed on an extension-definition-id. We model both branches as
    optional and rely on JSON Schema (via ``parse_external``) when
    the shape needs enforcing — the wrapper's job is round-tripping,
    not re-litigating the spec's own constraints.
    """

    type: Literal["marking-definition"] = "marking-definition"
    spec_version: Literal["2.1"] = "2.1"
    id: str
    created: datetime
    created_by_ref: str | None = None
    name: str | None = None
    definition_type: str | None = None
    definition: dict[str, Any] | None = None
    external_references: list[ExternalReference] | None = None
    object_marking_refs: list[str] | None = None
    granular_markings: list[GranularMarking] | None = None

    @field_serializer("created", when_used="always")
    def _serialise_created(self, value: datetime) -> str:
        return _serialise_stix_timestamp(value)


# ---------------------------------------------------------------------------
# Discriminated union of every STIX object type the wrapper models.
#
# Per the design note's 2026-05-07 amendment this is INTERNAL: the public
# `prow.stix` surface re-exports specific types only. The persister and the
# bundle constructor are the legitimate consumers; everyone else takes
# concrete types in their signatures.
# ---------------------------------------------------------------------------

_StixObject = Annotated[
    (
        AttackPattern
        | Campaign
        | DomainName
        | EmailAddr
        | File
        | Identity
        | Indicator
        | IntrusionSet
        | Ipv4Addr
        | Ipv6Addr
        | Malware
        | MarkingDefinition
        | ObservedData
        | Relationship
        | Report
        | Sighting
        | Software
        | ThreatActor
        | Tool
        | Url
        | Vulnerability
    ),
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Bundle.
# ---------------------------------------------------------------------------


class Bundle(_StixCommon):
    """STIX Bundle — the over-the-wire transport unit.

    STIX 2.1 bundles intentionally do not carry ``spec_version``;
    each contained object declares its own.
    """

    type: Literal["bundle"] = "bundle"
    id: str
    objects: list[_StixObject] = Field(min_length=1)
