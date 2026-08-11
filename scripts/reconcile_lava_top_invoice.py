from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from datetime import datetime
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
from app.services.payment_delivery_orchestration_service import (  # noqa: E402
    reconcile_payment_and_deliver,
)
from app.services.payment_reconciliation_service import (  # noqa: E402
    PaymentReconciliationError,
    PaymentReconciliationOutcome,
    record_non_terminal_payment_check,
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
    checked_at: datetime | None = None,
) -> PaymentReconciliationOutcome:
    """Query one provider invoice and reuse authoritative domain reconciliation."""

    invoice = invoice_lookup(external_payment_id)
    event = normalize_lava_top_invoice(invoice)
    if event is None:
        record_non_terminal_payment_check(
            db,
            payment_provider="lava_top",
            external_payment_id=invoice.invoice_id,
            expected_sale_id=sale_id,
            amount=invoice.amount,
            currency=invoice.currency,
            checked_at=checked_at,
        )
        db.commit()
        raise InvoiceNotTerminalError(
            "Lava.top invoice is not terminal; non-terminal check recorded."
        )
    outcome = reconcile_payment_and_deliver(
        db,
        event,
        expected_sale_id=sale_id,
    )
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
