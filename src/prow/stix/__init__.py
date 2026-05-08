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

"""STIX 2.1 boundary types, validators, helpers, and well-known constants.

The public surface intentionally excludes:

* :mod:`prow.stix._stix2_adapter` — the sole boundary to the upstream
  ``stix2`` library, internal by ADR-0009 (2026-05-07 amendment).
* The ``_StixObject`` discriminated union from
  :mod:`prow.stix.types` — internal by the design note's 2026-05-07
  amendment. Public API exposes specific types.
* Schema-loader internals (:mod:`prow.stix._validate` keeps its
  underscore prefix; only the three callables below are re-exported).

Anything not listed in :data:`__all__` is implementation detail and
may change without notice.
"""

from prow.stix._validate import (
    StixValidationError,
    validate_many,
    validate_stix_object,
)
from prow.stix.helpers import (
    bundle,
    domain_observable,
    email_addr_observable,
    file_observable,
    indicator,
    ipv4_observable,
    ipv6_observable,
    relationship,
    url_observable,
)
from prow.stix.markings import (
    TLP_2_0_EXTENSION_DEFINITION_ID,
    TLP_AMBER,
    TLP_AMBER_STRICT,
    TLP_CLEAR,
    TLP_GREEN,
    TLP_LEVELS,
    TLP_RED,
    label_to_tlp_id,
    tlp_id_to_label,
)
from prow.stix.types import (
    AttackPattern,
    Bundle,
    Campaign,
    DomainName,
    EmailAddr,
    ExternalReference,
    File,
    GranularMarking,
    Identity,
    Indicator,
    IntrusionSet,
    Ipv4Addr,
    Ipv6Addr,
    KillChainPhase,
    Malware,
    MarkingDefinition,
    ObservedData,
    Relationship,
    Report,
    Sighting,
    Software,
    ThreatActor,
    Tool,
    Url,
    Vulnerability,
)

__all__ = [
    "TLP_2_0_EXTENSION_DEFINITION_ID",
    "TLP_AMBER",
    "TLP_AMBER_STRICT",
    "TLP_CLEAR",
    "TLP_GREEN",
    "TLP_LEVELS",
    "TLP_RED",
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
    "StixValidationError",
    "ThreatActor",
    "Tool",
    "Url",
    "Vulnerability",
    "bundle",
    "domain_observable",
    "email_addr_observable",
    "file_observable",
    "indicator",
    "ipv4_observable",
    "ipv6_observable",
    "label_to_tlp_id",
    "relationship",
    "tlp_id_to_label",
    "url_observable",
    "validate_many",
    "validate_stix_object",
]
