from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy.exc import SQLAlchemyError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.services.lava_top.client import (  # noqa: E402
    LavaTopProviderError,
    get_invoice,
)
from app.services.payment_reconciliation_service import (  # noqa: E402
    PaymentReconciliationError,
    PaymentReconciliationOutcome,
    reconcile_payment_event,
)
from app.services.webhooks.payload_normalizers.lava_top_payment_normalizer import (  # noqa: E402
    normalize_lava_top_invoice,
)


class InvoiceNotTerminalError(Exception):
    """Raised when manual verification finds no authoritative final outcome."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify and reconcile one explicit Lava.top invoice/Sale pair.",
    )
    parser.add_argument("--sale-id", required=True, type=int)
    parser.add_argument("--external-payment-id", required=True)
    return parser


def reconcile_lava_top_invoice(
    db: Session,
    *,
    sale_id: int,
    external_payment_id: str,
    invoice_lookup: Callable = get_invoice,
) -> PaymentReconciliationOutcome:
    """Query one provider invoice and reuse authoritative domain reconciliation."""

    invoice = invoice_lookup(external_payment_id)
    event = normalize_lava_top_invoice(invoice)
    if event is None:
        raise InvoiceNotTerminalError(
            "Lava.top invoice is not in a terminal payment state."
        )
    outcome = reconcile_payment_event(
        db,
        event,
        expected_sale_id=sale_id,
    )
    db.commit()
    return outcome


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    db = SessionLocal()
    try:
        outcome = reconcile_lava_top_invoice(
            db,
            sale_id=args.sale_id,
            external_payment_id=args.external_payment_id,
        )
    except (
        InvoiceNotTerminalError,
        LavaTopProviderError,
        PaymentReconciliationError,
        SQLAlchemyError,
    ) as exc:
        db.rollback()
        print(f"reconciliation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    else:
        print(f"reconciliation {outcome.result.value}: sale_id={outcome.sale_id}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
