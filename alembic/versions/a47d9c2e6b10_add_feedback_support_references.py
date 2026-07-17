"""add feedback support references

Revision ID: a47d9c2e6b10
Revises: b8f4a2d91c6e
Create Date: 2026-07-17 00:00:00.000000

"""

import secrets
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "a47d9c2e6b10"
down_revision: Union[str, Sequence[str], None] = "b8f4a2d91c6e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SUPPORT_REFERENCE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _generate_support_reference(existing: set[str]) -> str:
    while True:
        suffix = "".join(secrets.choice(SUPPORT_REFERENCE_ALPHABET) for _ in range(8))
        reference = f"DL-{suffix}"
        if reference not in existing:
            existing.add(reference)
            return reference


def upgrade() -> None:
    op.alter_column(
        "feedback_messages",
        "type",
        existing_type=sa.String(length=20),
        type_=sa.String(length=50),
        existing_nullable=False,
    )
    op.add_column(
        "feedback_messages",
        sa.Column("support_reference", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "download_entitlements",
        sa.Column("support_reference", sa.String(length=11), nullable=True),
    )

    connection = op.get_bind()
    entitlement_table = sa.table(
        "download_entitlements",
        sa.column("id", sa.Integer()),
        sa.column("support_reference", sa.String(length=11)),
    )
    entitlement_ids = connection.execute(sa.select(entitlement_table.c.id)).scalars()
    existing: set[str] = set()

    for entitlement_id in entitlement_ids:
        connection.execute(
            entitlement_table.update()
            .where(entitlement_table.c.id == entitlement_id)
            .values(support_reference=_generate_support_reference(existing))
        )

    op.alter_column(
        "download_entitlements",
        "support_reference",
        existing_type=sa.String(length=11),
        nullable=False,
    )
    op.create_index(
        "ix_download_entitlements_support_reference",
        "download_entitlements",
        ["support_reference"],
        unique=True,
    )


def downgrade() -> None:
    connection = op.get_bind()
    feedback_table = sa.table(
        "feedback_messages",
        sa.column("type", sa.String(length=50)),
    )
    incompatible_count = connection.scalar(
        sa.select(sa.func.count())
        .select_from(feedback_table)
        .where(sa.func.length(feedback_table.c.type) > 20)
    )
    if incompatible_count:
        raise RuntimeError(
            "Cannot safely downgrade while feedback types longer than 20 "
            "characters exist."
        )

    op.drop_index(
        "ix_download_entitlements_support_reference",
        table_name="download_entitlements",
    )
    op.drop_column("download_entitlements", "support_reference")
    op.drop_column("feedback_messages", "support_reference")
    op.alter_column(
        "feedback_messages",
        "type",
        existing_type=sa.String(length=50),
        type_=sa.String(length=20),
        existing_nullable=False,
    )
