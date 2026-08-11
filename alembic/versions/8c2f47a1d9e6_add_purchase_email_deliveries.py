"""add purchase email deliveries

Revision ID: 8c2f47a1d9e6
Revises: 3e91b7c2a6d4
Create Date: 2026-08-11 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "8c2f47a1d9e6"
down_revision: Union[str, Sequence[str], None] = "3e91b7c2a6d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "purchase_email_deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sale_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sending_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("last_error", sa.String(length=2000), nullable=True),
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
            name="ck_purchase_email_deliveries_attempt_count_non_negative",
        ),
        sa.CheckConstraint(
            "status IN "
            "('pending', 'sending', 'sent', 'failed', 'reconciliation_required')",
            name="ck_purchase_email_deliveries_status",
        ),
        sa.ForeignKeyConstraint(
            ["sale_id"],
            ["sales.id"],
            name="fk_purchase_email_deliveries_sale_id_sales",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_purchase_email_deliveries_sale_id",
        "purchase_email_deliveries",
        ["sale_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_purchase_email_deliveries_sale_id",
        table_name="purchase_email_deliveries",
    )
    op.drop_table("purchase_email_deliveries")
