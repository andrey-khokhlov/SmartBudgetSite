"""restore database schema parity

Revision ID: 2f6a9d7c4e10
Revises: f6d2c8a91e34
Create Date: 2026-07-21 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "2f6a9d7c4e10"
down_revision: Union[str, Sequence[str], None] = "f6d2c8a91e34"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CONSULTATION_TIMESTAMP_COLUMNS = (
    ("created_at", False),
    ("expires_at", False),
    ("booked_at", True),
)


def upgrade() -> None:
    for column_name, nullable in _CONSULTATION_TIMESTAMP_COLUMNS:
        op.alter_column(
            "consultation_entitlements",
            column_name,
            existing_type=sa.DateTime(timezone=False),
            type_=sa.DateTime(timezone=True),
            existing_nullable=nullable,
            postgresql_using=f"{column_name} AT TIME ZONE 'UTC'",
        )


def downgrade() -> None:
    for column_name, nullable in _CONSULTATION_TIMESTAMP_COLUMNS:
        op.alter_column(
            "consultation_entitlements",
            column_name,
            existing_type=sa.DateTime(timezone=True),
            type_=sa.DateTime(timezone=False),
            existing_nullable=nullable,
            postgresql_using=f"{column_name} AT TIME ZONE 'UTC'",
        )
