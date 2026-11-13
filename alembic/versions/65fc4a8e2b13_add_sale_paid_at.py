"""Add the authoritative Sale payment confirmation timestamp."""

import sqlalchemy as sa
from alembic import op

revision = "65fc4a8e2b13"
down_revision = "d7e45fa921c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sales", sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.execute("LOCK TABLE sales IN ACCESS EXCLUSIVE MODE")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM sales WHERE paid_at IS NOT NULL) THEN
                RAISE EXCEPTION 'Downgrade blocked: Sale payment timestamps would be lost.'
                    USING HINT = 'Keep this revision or archive and explicitly migrate the timestamps.';
            END IF;
        END $$;
    """)
    op.drop_column("sales", "paid_at")
