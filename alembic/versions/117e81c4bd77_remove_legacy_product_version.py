"""remove legacy product version

Revision ID: 117e81c4bd77
Revises: 3b1c4f189918
Create Date: 2026-07-05 15:20:02.194072

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '117e81c4bd77'
down_revision: Union[str, Sequence[str], None] = '3b1c4f189918'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Remove legacy product-level version field."""

    op.drop_constraint(
        "uq_products_slug_edition_version",
        "products",
        type_="unique",
    )

    op.drop_column("products", "version")


def downgrade() -> None:
    """Restore legacy product-level version field."""

    op.add_column(
        "products",
        sa.Column(
            "version",
            sa.String(length=50),
            nullable=False,
            server_default="legacy",
        ),
    )

    op.create_unique_constraint(
        "uq_products_slug_edition_version",
        "products",
        ["slug", "edition", "version"],
    )

    op.alter_column(
        "products",
        "version",
        server_default=None,
    )
