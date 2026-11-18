"""Preserve consultation cancellation and refund exception evidence."""

import sqlalchemy as sa
from alembic import op

revision = "5c2c71bc5f4a"
down_revision = "197e36fb4bc1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "consultation_cancellations",
        sa.Column(
            "entitlement_id",
            sa.Integer(),
            sa.ForeignKey("consultation_entitlements.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "refund_request_id",
            sa.Integer(),
            sa.ForeignKey("refund_requests.id", ondelete="RESTRICT"),
        ),
        sa.Column("access_closed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_uri", sa.String(500)),
        sa.Column("invitee_uri", sa.String(500)),
        sa.Column("provider_outcome", sa.String(32)),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "refund_operations",
        sa.Column("exceptional_confirmed_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "refund_operations", sa.Column("exceptional_confirmation_reason", sa.Text())
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM consultation_cancellations) OR "
            "EXISTS (SELECT 1 FROM refund_operations WHERE exceptional_confirmed_at IS NOT NULL)"
        )
    ):
        raise RuntimeError(
            "Downgrade blocked: consultation cancellation evidence would be lost."
        )
    op.drop_column("refund_operations", "exceptional_confirmation_reason")
    op.drop_column("refund_operations", "exceptional_confirmed_at")
    op.drop_table("consultation_cancellations")
