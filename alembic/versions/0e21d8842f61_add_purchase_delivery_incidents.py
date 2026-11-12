"""Add purchase delivery incidents.

Revision ID: 0e21d8842f61
Revises: eb63c5a92f10
"""

import sqlalchemy as sa
from alembic import op

revision = "0e21d8842f61"
down_revision = "eb63c5a92f10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "purchase_delivery_incidents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sale_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("severity", sa.String(8), nullable=False),
        sa.Column("first_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "severity IN ('error', 'warning')",
            name="ck_purchase_delivery_incidents_severity",
        ),
    )
    op.create_index(
        "uq_purchase_delivery_incidents_open",
        "purchase_delivery_incidents",
        ["sale_id", "subject_id", "kind"],
        unique=True,
        postgresql_where=sa.text("resolved_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("purchase_delivery_incidents")
