import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.enums import PaymentStatus
from app.models.refund_operation import RefundOperation
from app.models.sale import Sale
from app.services.refund_service import (
    RefundConflictError,
    confirm_full_refund,
    start_full_refund,
)
from tests.services.test_refund_service import VERIFIED_ALTERNATIVE, create_sale
from tests.test_purchase_email_failure_classification_postgres import (  # noqa: F401
    disposable_postgres,
)

PREVIOUS = "4a2d8c71ef36"
REVISION = "1c6ea8b50d37"


def test_refund_confirmation_migration_retains_legacy_history_and_serializes_methods(
    disposable_postgres,  # noqa: F811
):
    engine, env = disposable_postgres

    def alembic(*args, succeeds=True):
        result = subprocess.run(
            [sys.executable, "-B", "-m", "alembic", *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
        )
        assert (result.returncode == 0) == succeeds, result.stderr
        return result

    alembic("upgrade", PREVIOUS)
    with engine.begin() as connection:
        legacy_id = connection.scalar(
            text(
                "INSERT INTO sales (sale_reference, customer_email, amount, currency, "
                "payment_status, payment_provider, external_payment_id) VALUES "
                "('PAY-ABCDEFGHIJKLMN', 'legacy@example.com', 40, 'EUR', 'refunded', "
                "'lava_top', 'legacy-invoice') RETURNING id"
            )
        )
        legacy_time = connection.scalar(
            text(
                "INSERT INTO refund_operations (sale_id, status, amount, currency, "
                "payment_provider, external_payment_id, confirmed_at) VALUES "
                "(:sale_id, 'confirmed', 40, 'EUR', 'lava_top', 'legacy-invoice', now()) "
                "RETURNING confirmed_at"
            ),
            {"sale_id": legacy_id},
        )

    alembic("upgrade", REVISION)
    alembic("check")
    with Session(engine) as db:
        verified = confirm_full_refund(
            db, sale_id=legacy_id, provider_refund_verified=True
        )
        assert verified.result == "idempotent"
        assert verified.operation.confirmation_method is None
        assert verified.operation.confirmed_at == legacy_time
        db.rollback()
        with pytest.raises(RefundConflictError, match="cannot change"):
            confirm_full_refund(
                db, sale_id=legacy_id, alternative_verification=VERIFIED_ALTERNATIVE
            )

    alembic("downgrade", PREVIOUS)
    assert "confirmation_method" not in {
        column["name"] for column in inspect(engine).get_columns("refund_operations")
    }
    alembic("upgrade", REVISION)
    with Session(engine) as db:
        sale, grant, _ = create_sale(db)
        sale_id, grant_id = sale.id, grant.id
        operation_id = start_full_refund(db, sale_id=sale_id).id
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE refund_operations SET confirmation_method = 'alternative_transfer' "
                "WHERE id = :operation_id"
            ),
            {"operation_id": operation_id},
        )

    ready = Barrier(2, timeout=10)

    def confirm(method, **verification):
        with Session(engine) as db:
            ready.wait()
            try:
                result = confirm_full_refund(db, sale_id=sale_id, **verification)
            except RefundConflictError:
                return method, "conflict"
            return method, result.result

    with ThreadPoolExecutor(max_workers=2) as pool:
        original = pool.submit(
            confirm, "original_provider", provider_refund_verified=True
        )
        alternative = pool.submit(
            confirm,
            "alternative_transfer",
            alternative_verification=VERIFIED_ALTERNATIVE,
        )
        outcomes = dict((original.result(timeout=10), alternative.result(timeout=10)))
    assert set(outcomes.values()) == {"applied", "conflict"}
    with Session(engine) as db:
        operation = db.get(RefundOperation, operation_id)
        assert outcomes[operation.confirmation_method] == "applied"
        sale = db.get(Sale, sale_id)
        assert sale.payment_status == PaymentStatus.REFUNDED
        assert sale.items[0].download_entitlement.id == grant_id
        assert sale.items[0].download_entitlement.status == "cancelled"

    blocked = alembic("downgrade", PREVIOUS, succeeds=False)
    assert (
        "Downgrade blocked: refund confirmation method history exists."
        in blocked.stderr
    )
    alembic("check")
