"""add download entitlements

Revision ID: b8f4a2d91c6e
Revises: 4d7b0c31a8e2
Create Date: 2026-07-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8f4a2d91c6e"
down_revision: Union[str, Sequence[str], None] = "4d7b0c31a8e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "download_entitlements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sale_item_id", sa.Integer(), nullable=False),
        sa.Column("release_id", sa.Integer(), nullable=False),
        sa.Column("download_token", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("first_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_download_entitlements_attempt_count_non_negative",
        ),
        sa.CheckConstraint(
            "status IN ('available', 'completed', 'expired', 'cancelled')",
            name="ck_download_entitlements_status",
        ),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["product_releases.id"],
            name="fk_download_entitlements_release_id_product_releases",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["sale_item_id"],
            ["sale_items.id"],
            name="fk_download_entitlements_sale_item_id_sale_items",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_download_entitlements_release_id",
        "download_entitlements",
        ["release_id"],
        unique=False,
    )
    op.create_index(
        "ix_download_entitlements_download_token",
        "download_entitlements",
        ["download_token"],
        unique=True,
    )
    op.create_index(
        "ix_download_entitlements_sale_item_id",
        "download_entitlements",
        ["sale_item_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_download_entitlements_sale_item_id",
        table_name="download_entitlements",
    )
    op.drop_index(
        "ix_download_entitlements_download_token",
        table_name="download_entitlements",
    )
    op.drop_index(
        "ix_download_entitlements_release_id",
        table_name="download_entitlements",
    )
    op.drop_table("download_entitlements")
