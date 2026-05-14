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

"""Postgres persistence layer (SQLAlchemy 2 async + Alembic)."""

from __future__ import annotations

from prow.db.config import DatabaseSettings, load_database_settings
from prow.db.emit_handler import (
    create_db_emit_handler,
    create_inprocess_db_emit_handler,
)
from prow.db.ingest import (
    ingest_stix_bundle,
    stix_validation_error_to_failures,
    validate_and_partition_bundle,
)
from prow.db.models import Base, ConnectorStateRow, StixObjectRow
from prow.db.repositories import (
    ConnectorStateRepository,
    SqlAlchemyConnectorStateRepository,
    SqlAlchemyStixObjectRepository,
    StixObjectRepository,
)
from prow.db.session import (
    check_database,
    create_async_engine_from_settings,
    create_async_sessionmaker,
    dispose_engine,
    session_scope,
)
from prow.db.stix_fields import (
    extract_stix_persistence_fields,
    parse_stix_datetime,
    relationship_triple_key,
)

__all__ = [
    "Base",
    "ConnectorStateRepository",
    "ConnectorStateRow",
    "DatabaseSettings",
    "SqlAlchemyConnectorStateRepository",
    "SqlAlchemyStixObjectRepository",
    "StixObjectRepository",
    "StixObjectRow",
    "check_database",
    "create_async_engine_from_settings",
    "create_async_sessionmaker",
    "create_db_emit_handler",
    "create_inprocess_db_emit_handler",
    "dispose_engine",
    "extract_stix_persistence_fields",
    "ingest_stix_bundle",
    "load_database_settings",
    "parse_stix_datetime",
    "relationship_triple_key",
    "session_scope",
    "stix_validation_error_to_failures",
    "validate_and_partition_bundle",
]
