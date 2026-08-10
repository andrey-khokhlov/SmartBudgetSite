"""allow shared provider offer identifiers

Revision ID: 3e91b7c2a6d4
Revises: 7b91c5e2a4f0
Create Date: 2026-08-10 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

revision: str = "3e91b7c2a6d4"
down_revision: Union[str, Sequence[str], None] = "7b91c5e2a4f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_payment_provider_offers_provider_external_offer_id",
        "payment_provider_offers",
        type_="unique",
    )


def downgrade() -> None:
    op.create_unique_constraint(
        "uq_payment_provider_offers_provider_external_offer_id",
        "payment_provider_offers",
        ["provider", "external_offer_id"],
    )
