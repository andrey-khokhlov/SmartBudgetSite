"""Backfill permanent public purchase references."""

import secrets

import sqlalchemy as sa
from alembic import op

revision = "8c40f6a2e517"
down_revision = "65fc4a8e2b13"
branch_labels = None
depends_on = None

ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def upgrade() -> None:
    op.execute("LOCK TABLE sales IN ACCESS EXCLUSIVE MODE")
    op.execute("LOCK TABLE purchase_email_deliveries IN SHARE ROW EXCLUSIVE MODE")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM purchase_email_deliveries WHERE status = 'sending') THEN
                RAISE EXCEPTION 'Reconcile sending purchase emails before the purchase reference cutover';
            END IF;
        END $$;
    """)
    op.add_column("sales", sa.Column("sale_reference", sa.String(18), nullable=True))
    sales = sa.table(
        "sales", sa.column("id", sa.Integer), sa.column("sale_reference", sa.String(18))
    )
    connection = op.get_bind()
    allocated: set[str] = set()
    for sale_id in connection.scalars(sa.select(sales.c.id)):
        while True:
            reference = "PAY-" + "".join(secrets.choice(ALPHABET) for _ in range(14))
            if reference not in allocated:
                break
        allocated.add(reference)
        connection.execute(
            sales.update().where(sales.c.id == sale_id).values(sale_reference=reference)
        )
    op.alter_column("sales", "sale_reference", existing_type=sa.String(18), nullable=False)
    op.create_unique_constraint("uq_sales_sale_reference", "sales", ["sale_reference"])


def downgrade() -> None:
    op.execute("LOCK TABLE sales IN ACCESS EXCLUSIVE MODE")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM sales) THEN
                RAISE EXCEPTION 'Downgrade blocked: permanent purchase references would be lost.';
            END IF;
        END $$;
    """)
    op.drop_constraint("uq_sales_sale_reference", "sales", type_="unique")
    op.drop_column("sales", "sale_reference")
