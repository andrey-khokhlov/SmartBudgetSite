"""Persist download recovery audit and the separate recovery email state."""

import sqlalchemy as sa

from alembic import op

revision = "4a2d8c71ef36"
down_revision = "8e21d4f6ab93"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "purchase_access_recoveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "sale_id",
            sa.Integer(),
            sa.ForeignKey("sales.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "entitlement_id",
            sa.Integer(),
            sa.ForeignKey("download_entitlements.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("request_id", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("verification_method", sa.String(32), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("previous_email", sa.String(200)),
        sa.Column("recipient", sa.String(200), nullable=False),
        sa.Column("previous_status", sa.String(20), nullable=False),
        sa.Column("previous_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("previous_attempt_count", sa.Integer(), nullable=False),
        sa.Column("previous_first_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("previous_last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("delivery_status", sa.String(32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("first_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("payload_fingerprint", sa.String(64)),
        sa.Column("provider_message_id", sa.String(255)),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(32)),
        sa.UniqueConstraint(
            "sale_id", "request_id", name="uq_purchase_access_recovery_request"
        ),
        sa.CheckConstraint(
            "delivery_status IN ('ready', 'sending', 'accepted', 'failed', "
            "'ambiguous', 'reconciliation_required')",
            name="ck_purchase_access_recovery_delivery_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND previous_attempt_count >= 0",
            name="ck_purchase_access_recovery_attempt_counts",
        ),
    )
    op.create_index(
        "ix_purchase_access_recoveries_sale_id",
        "purchase_access_recoveries",
        ["sale_id"],
    )


def downgrade() -> None:
    op.execute("LOCK TABLE purchase_access_recoveries IN ACCESS EXCLUSIVE MODE")
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM purchase_access_recoveries) THEN
                RAISE EXCEPTION 'Downgrade blocked: purchase access recovery history exists.';
            END IF;
        END $$;
        """)
    op.drop_table("purchase_access_recoveries")
