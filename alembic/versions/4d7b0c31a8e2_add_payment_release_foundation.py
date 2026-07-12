"""add payment release foundation

Revision ID: 4d7b0c31a8e2
Revises: 6a6f34df3e70
Create Date: 2026-07-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4d7b0c31a8e2"
down_revision: Union[str, Sequence[str], None] = "6a6f34df3e70"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sale_items",
        sa.Column("product_release_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_sale_items_product_release_id_product_releases",
        "sale_items",
        "product_releases",
        ["product_release_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_sale_items_product_release_id",
        "sale_items",
        ["product_release_id"],
        unique=False,
    )
    op.create_index(
        "uq_sales_payment_provider_external_payment_id",
        "sales",
        ["payment_provider", "external_payment_id"],
        unique=True,
        postgresql_where=sa.text("external_payment_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_sales_payment_provider_external_payment_id",
        table_name="sales",
    )
    op.drop_index("ix_sale_items_product_release_id", table_name="sale_items")
    op.drop_constraint(
        "fk_sale_items_product_release_id_product_releases",
        "sale_items",
        type_="foreignkey",
    )
    op.drop_column("sale_items", "product_release_id")
