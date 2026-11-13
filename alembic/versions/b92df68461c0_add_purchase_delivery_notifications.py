"""Add the purchase delivery notification outbox."""

import sqlalchemy as sa
from alembic import op

revision = "b92df68461c0"
down_revision = "78e0b9842bd1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "purchase_delivery_notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("incident_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(8), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["incident_id"], ["purchase_delivery_incidents.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "incident_id",
            "channel",
            name="uq_purchase_delivery_notifications_incident_channel",
        ),
        sa.CheckConstraint(
            "channel IN ('smtp', 'telegram')",
            name="ck_purchase_delivery_notifications_channel",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name="ck_purchase_delivery_notifications_attempts"
        ),
    )


def downgrade() -> None:
    op.execute("LOCK TABLE purchase_delivery_notifications IN ACCESS EXCLUSIVE MODE")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM purchase_delivery_notifications) THEN
                RAISE EXCEPTION 'Downgrade blocked: purchase delivery notification history would be lost.'
                    USING HINT = 'Keep this revision or archive and explicitly migrate the outbox before downgrading.';
            END IF;
        END $$;
        """
    )
    op.drop_table("purchase_delivery_notifications")
