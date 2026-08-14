"""add refund operations

Revision ID: 9d4c2a7e6f10
Revises: 7c2a4e8f91b0
Create Date: 2026-08-14 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "9d4c2a7e6f10"
down_revision: Union[str, Sequence[str], None] = "7c2a4e8f91b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "refund_operations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sale_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("payment_provider", sa.String(length=50), nullable=False),
        sa.Column("external_payment_id", sa.String(length=200), nullable=False),
        sa.Column("provider_refund_id", sa.String(length=200), nullable=True),
        sa.Column("provider_status", sa.String(length=100), nullable=True),
        sa.Column("provider_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "reconciliation_required_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'confirmed', 'reconciliation_required')",
            name="ck_refund_operations_status",
        ),
        sa.CheckConstraint("amount > 0", name="ck_refund_operations_amount_positive"),
        sa.ForeignKeyConstraint(["sale_id"], ["sales.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_refund_operations_sale_id"),
        "refund_operations",
        ["sale_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_refund_operations_sale_id"), table_name="refund_operations")
    op.drop_table("refund_operations")
