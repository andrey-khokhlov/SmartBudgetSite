"""add payment provider offers

Revision ID: 7b91c5e2a4f0
Revises: 2f6a9d7c4e10
Create Date: 2026-08-09 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "7b91c5e2a4f0"
down_revision: Union[str, Sequence[str], None] = "2f6a9d7c4e10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payment_provider_offers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("external_offer_id", sa.String(length=200), nullable=False),
        sa.CheckConstraint(
            "length(trim(provider)) > 0",
            name="ck_payment_provider_offers_provider_non_empty",
        ),
        sa.CheckConstraint(
            "length(trim(external_offer_id)) > 0",
            name="ck_payment_provider_offers_external_offer_id_non_empty",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "product_id",
            "provider",
            name="uq_payment_provider_offers_product_provider",
        ),
        sa.UniqueConstraint(
            "provider",
            "external_offer_id",
            name="uq_payment_provider_offers_provider_external_offer_id",
        ),
    )
    op.create_index(
        op.f("ix_payment_provider_offers_product_id"),
        "payment_provider_offers",
        ["product_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_payment_provider_offers_product_id"),
        table_name="payment_provider_offers",
    )
    op.drop_table("payment_provider_offers")
