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

"""Initial v0.1 persistence: ``stix_objects`` + ``connector_state``.

Relationship SDOs are stored only in ``stix_objects`` (no ``stix_relationships`` table
and no global uniqueness on ``(source_ref, relationship_type, target_ref)``) so
alternate STIX relationship identities remain first-class rows.

See docs/design/persister.md with the relationship-storage amendment from the v0.1
implementation pass.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260513_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stix_objects",
        sa.Column(
            "row_id",
            sa.BigInteger(),
            sa.Identity(always=False),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("spec_version", sa.Text(), nullable=False),
        sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("modified", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_ref", sa.Text(), nullable=True),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("confidence", sa.SmallInteger(), nullable=True),
        sa.Column("source_connector_instance_id", sa.Text(), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 100)",
            name="ck_stix_objects_confidence_range",
        ),
    )

    op.create_index("ix_stix_objects_type", "stix_objects", ["type"], unique=False)
    op.create_index(
        "ix_stix_objects_connector",
        "stix_objects",
        ["source_connector_instance_id"],
        unique=False,
    )
    op.create_index("ix_stix_objects_ingested_at", "stix_objects", ["ingested_at"], unique=False)
    op.create_index("ix_stix_objects_created", "stix_objects", ["created"], unique=False)
    op.create_index("ix_stix_objects_modified", "stix_objects", ["modified"], unique=False)

    op.execute(
        sa.text(
            "CREATE INDEX ix_stix_objects_indicator_pattern "
            "ON stix_objects ((raw->>'pattern')) WHERE type = 'indicator'"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_stix_objects_vuln_name_lower "
            "ON stix_objects (lower(raw->>'name')) WHERE type = 'vulnerability'"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_stix_objects_malware_name_lower "
            "ON stix_objects (lower(raw->>'name')) WHERE type = 'malware'"
        )
    )

    op.create_index(
        "ux_stix_objects_versioned_id_modified",
        "stix_objects",
        ["id", "modified"],
        unique=True,
        postgresql_where=sa.text("modified IS NOT NULL"),
    )
    op.create_index(
        "ux_stix_objects_sco_id",
        "stix_objects",
        ["id"],
        unique=True,
        postgresql_where=sa.text("modified IS NULL"),
    )

    op.create_table(
        "connector_state",
        sa.Column("connector_instance_id", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("connector_instance_id", "key"),
    )


def downgrade() -> None:
    op.drop_table("connector_state")
    op.drop_table("stix_objects")
