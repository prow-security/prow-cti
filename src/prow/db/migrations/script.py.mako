"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""

from collections.abc import Sequence

from alembic import op


# revision identifiers, used by Alembic.
revision: str | None = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    raise NotImplementedError


def downgrade() -> None:
    raise NotImplementedError
