"""Add standalone service payment provider offers.

Revision ID: 4b1e9d62c730
Revises: 9d4c2a7e6f10
"""

import sqlalchemy as sa
from alembic import op

revision = "4b1e9d62c730"
down_revision = "9d4c2a7e6f10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "service_payment_provider_offers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("service_addon_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("external_offer_id", sa.String(length=200), nullable=False),
        sa.CheckConstraint(
            "length(trim(provider)) > 0",
            name="ck_service_payment_provider_offers_provider_non_empty",
        ),
        sa.CheckConstraint(
            "length(trim(external_offer_id)) > 0",
            name="ck_service_payment_provider_offers_external_offer_id_non_empty",
        ),
        sa.ForeignKeyConstraint(
            ["service_addon_id"], ["service_addons.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "service_addon_id",
            "provider",
            name="uq_service_payment_provider_offers_service_provider",
        ),
    )
    op.create_index(
        "ix_service_payment_provider_offers_service_addon_id",
        "service_payment_provider_offers",
        ["service_addon_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_service_payment_provider_offers_service_addon_id",
        table_name="service_payment_provider_offers",
    )
    op.drop_table("service_payment_provider_offers")
