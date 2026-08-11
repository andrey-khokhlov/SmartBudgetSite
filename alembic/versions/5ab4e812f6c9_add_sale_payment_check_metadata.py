"""add Sale payment check metadata

Revision ID: 5ab4e812f6c9
Revises: 8c2f47a1d9e6
Create Date: 2026-08-11 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "5ab4e812f6c9"
down_revision: Union[str, Sequence[str], None] = "8c2f47a1d9e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sales",
        sa.Column("payment_last_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "sales",
        sa.Column("payment_last_check_result", sa.String(length=32), nullable=True),
    )
    op.create_check_constraint(
        "ck_sales_payment_last_check_metadata",
        "sales",
        "(payment_last_checked_at IS NULL AND payment_last_check_result IS NULL) "
        "OR (payment_last_checked_at IS NOT NULL "
        "AND payment_last_check_result IS NOT NULL "
        "AND payment_last_check_result = 'non_terminal')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_sales_payment_last_check_metadata",
        "sales",
        type_="check",
    )
    op.drop_column("sales", "payment_last_check_result")
    op.drop_column("sales", "payment_last_checked_at")
