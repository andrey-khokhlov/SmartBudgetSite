"""Add Calendly Share ownership to consultation entitlements."""

import sqlalchemy as sa
from alembic import op

revision = "6f3c1a8d905e"
down_revision = "24d760e4bc31"
branch_labels = None
depends_on = None

TABLE = "consultation_entitlements"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("provisioning_reference", sa.String(22)))
    op.add_column(
        TABLE, sa.Column("provisioning_claimed_at", sa.DateTime(timezone=True))
    )
    op.add_column(TABLE, sa.Column("calendly_event_type_uri", sa.String(500)))
    op.add_column(TABLE, sa.Column("calendly_share_uri", sa.String(500)))
    op.add_column(TABLE, sa.Column("calendly_booking_url", sa.String(2048)))
    op.create_unique_constraint(
        "uq_consultation_entitlements_provisioning_reference",
        TABLE,
        ["provisioning_reference"],
    )
    op.create_unique_constraint(
        "uq_consultation_entitlements_calendly_share_uri", TABLE, ["calendly_share_uri"]
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM consultation_entitlements "
            "WHERE provisioning_claimed_at IS NOT NULL)"
        )
    ):
        raise RuntimeError("Downgrade blocked: Calendly Share ownership would be lost.")
    op.drop_constraint(
        "uq_consultation_entitlements_calendly_share_uri", TABLE, type_="unique"
    )
    op.drop_constraint(
        "uq_consultation_entitlements_provisioning_reference", TABLE, type_="unique"
    )
    for name in (
        "calendly_booking_url",
        "calendly_share_uri",
        "calendly_event_type_uri",
        "provisioning_claimed_at",
        "provisioning_reference",
    ):
        op.drop_column(TABLE, name)
