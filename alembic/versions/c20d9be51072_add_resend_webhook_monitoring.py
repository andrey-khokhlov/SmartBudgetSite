"""Add Resend webhook receipts, provider state, and incident audit fields."""

import sqlalchemy as sa
from alembic import op

revision = "c20d9be51072"
down_revision = "a4c01eb72f56"
branch_labels = None
depends_on = None

DELIVERIES = "purchase_email_deliveries"
INCIDENTS = "purchase_delivery_incidents"
RECEIPTS = "resend_webhook_events"
OPEN_INDEX = "uq_purchase_delivery_incidents_open"
INCIDENT_KEY = ["sale_id", "subject_id", "kind"]


def upgrade() -> None:
    for column in (
        sa.Column("provider_delivery_status", sa.String(32)),
        sa.Column("provider_event_at", sa.DateTime(timezone=True)),
        sa.Column("provider_event_id", sa.String(128)),
        sa.Column("complaint_at", sa.DateTime(timezone=True)),
        sa.Column("complaint_event_id", sa.String(128)),
    ):
        op.add_column(DELIVERIES, column)
    op.create_table(
        RECEIPTS,
        sa.Column("svix_id", sa.String(128), primary_key=True),
        sa.Column("event_type", sa.String(32)),
        sa.Column("provider_email_id", sa.String(255)),
        sa.Column("delivery_id", sa.Integer()),
        sa.Column("provider_event_at", sa.DateTime(timezone=True)),
        sa.Column("first_received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(40), nullable=False),
    )
    op.create_index(
        "ix_resend_webhook_events_delivery_outcome",
        RECEIPTS,
        ["delivery_id", "outcome"],
    )
    op.create_index(
        "ix_resend_webhook_events_first_received_at", RECEIPTS, ["first_received_at"]
    )
    for column in (
        sa.Column(
            "requires_operator", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("originating_event_id", sa.String(128)),
        sa.Column("resolved_by", sa.String(128)),
        sa.Column("resolution_reason", sa.String(1000)),
    ):
        op.add_column(INCIDENTS, column)
    op.drop_index(OPEN_INDEX, table_name=INCIDENTS)
    op.create_index(
        OPEN_INDEX,
        INCIDENTS,
        INCIDENT_KEY,
        unique=True,
        postgresql_where=sa.text("resolved_at IS NULL AND requires_operator IS false"),
    )
    op.create_index(
        "uq_purchase_delivery_incidents_origin",
        INCIDENTS,
        [*INCIDENT_KEY, "originating_event_id"],
        unique=True,
    )


def downgrade() -> None:
    op.execute(
        "LOCK TABLE purchase_email_deliveries, resend_webhook_events, "
        "purchase_delivery_incidents IN ACCESS EXCLUSIVE MODE"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM purchase_delivery_incidents
                WHERE requires_operator OR originating_event_id IS NOT NULL
                    OR resolved_by IS NOT NULL OR resolution_reason IS NOT NULL
            ) OR EXISTS (
                SELECT 1 FROM resend_webhook_events
            ) OR EXISTS (
                SELECT 1 FROM purchase_email_deliveries
                WHERE provider_delivery_status IS NOT NULL OR provider_event_at IS NOT NULL
                    OR provider_event_id IS NOT NULL OR complaint_at IS NOT NULL
                    OR complaint_event_id IS NOT NULL
            ) THEN
                RAISE EXCEPTION 'Downgrade blocked: the previous schema cannot preserve Resend monitoring data.'
                    USING HINT = 'Keep this revision or archive and explicitly migrate the affected webhook receipts, provider state, and incident history before downgrading.';
            END IF;
        END $$;
        """
    )
    op.drop_index("uq_purchase_delivery_incidents_origin", table_name=INCIDENTS)
    op.drop_index(OPEN_INDEX, table_name=INCIDENTS)
    op.create_index(
        OPEN_INDEX,
        INCIDENTS,
        INCIDENT_KEY,
        unique=True,
        postgresql_where=sa.text("resolved_at IS NULL"),
    )
    for name in (
        "resolution_reason",
        "resolved_by",
        "originating_event_id",
        "requires_operator",
    ):
        op.drop_column(INCIDENTS, name)
    op.drop_table(RECEIPTS)
    for name in (
        "complaint_event_id",
        "complaint_at",
        "provider_event_id",
        "provider_event_at",
        "provider_delivery_status",
    ):
        op.drop_column(DELIVERIES, name)
