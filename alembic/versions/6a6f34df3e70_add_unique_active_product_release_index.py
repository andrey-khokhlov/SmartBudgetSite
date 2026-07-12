"""add unique active product release index

Revision ID: 6a6f34df3e70
Revises: 117e81c4bd77
Create Date: 2026-07-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6a6f34df3e70"
down_revision: Union[str, Sequence[str], None] = "117e81c4bd77"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Enforce at most one active release per product."""
    op.create_index(
        "uq_product_releases_active_product_id",
        "product_releases",
        ["product_id"],
        unique=True,
        postgresql_where=sa.text("is_active IS TRUE"),
    )


def downgrade() -> None:
    """Remove the active release uniqueness invariant."""
    op.drop_index(
        "uq_product_releases_active_product_id",
        table_name="product_releases",
    )
