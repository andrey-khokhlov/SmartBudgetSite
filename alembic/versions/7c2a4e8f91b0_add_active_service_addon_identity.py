"""add active service add-on business identity

Revision ID: 7c2a4e8f91b0
Revises: 5ab4e812f6c9
Create Date: 2026-08-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7c2a4e8f91b0"
down_revision: Union[str, Sequence[str], None] = "5ab4e812f6c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Enforce one active offer per full business identity."""
    op.create_index(
        "uq_service_addons_active_business_identity",
        "service_addons",
        [
            "family_slug",
            "package_code",
            "service_type",
            "usage_type",
            "currency_code",
        ],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )


def downgrade() -> None:
    """Remove the active consultation-offer uniqueness invariant."""
    op.drop_index(
        "uq_service_addons_active_business_identity",
        table_name="service_addons",
    )
