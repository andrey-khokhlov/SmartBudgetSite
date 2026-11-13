"""Add durable notification dispatch state."""

import sqlalchemy as sa
from alembic import op

revision = "d7e45fa921c0"
down_revision = "b92df68461c0"
branch_labels = None
depends_on = None

TABLE = "purchase_delivery_notifications"
CHECK = "ck_purchase_delivery_notifications_status"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column("status", sa.String(12), nullable=False, server_default="pending"),
    )
    op.add_column(TABLE, sa.Column("last_error", sa.String(24)))
    op.add_column(TABLE, sa.Column("skip_reason", sa.String(32)))
    op.execute(
        "UPDATE purchase_delivery_notifications SET status = 'delivered' WHERE delivered_at IS NOT NULL"
    )
    op.create_check_constraint(
        CHECK,
        TABLE,
        "status IN ('pending', 'sending', 'delivered', 'skipped', 'failed')",
    )


def downgrade() -> None:
    op.execute("LOCK TABLE purchase_delivery_notifications IN ACCESS EXCLUSIVE MODE")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM purchase_delivery_notifications
                WHERE status <> CASE WHEN delivered_at IS NULL THEN 'pending' ELSE 'delivered' END
                    OR last_error IS NOT NULL OR skip_reason IS NOT NULL
            ) THEN
                RAISE EXCEPTION 'Downgrade blocked: notification dispatcher state would be lost.'
                    USING HINT = 'Keep this revision or archive and explicitly migrate dispatcher state.';
            END IF;
        END $$;
    """)
    op.drop_constraint(CHECK, TABLE, type_="check")
    for column in ("skip_reason", "last_error", "status"):
        op.drop_column(TABLE, column)
