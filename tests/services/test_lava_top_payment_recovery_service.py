from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from email.utils import format_datetime

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.consultation_entitlement import ConsultationEntitlement
from app.models.download_entitlement import DownloadEntitlement
from app.models.lava_top_payment_recovery import (
    LavaTopPaymentRecovery,
    LavaTopRecoveryCooldown,
)
from app.models.product import Product
from app.models.product_release import ProductRelease
from app.models.purchase_email_delivery import PurchaseEmailDelivery
from app.models.sale import Sale
from app.models.service_addon import ServiceAddon
from app.schemas.webhooks import NormalizedPaymentEvent, PaymentOutcome
from app.services import lava_top_payment_recovery_service as recovery
from app.services.lava_top.client import LavaTopInvoiceDetails, LavaTopInvoiceStatus
from app.services.payment_reconciliation_service import reconcile_payment_event
from app.services.sale_service import (
    create_product_sale,
    create_service_sale_item,
    create_standalone_service_sale,
)

NOW = datetime(2026, 11, 12, 12, tzinfo=UTC)
COMPLETED = LavaTopInvoiceDetails(
    "invoice", LavaTopInvoiceStatus.COMPLETED, Decimal("50.00"), "RUB"
)


@pytest.fixture(autouse=True)
def isolate_recovery(monkeypatch):
    # SQLite tests cover the workflow. The PostgreSQL pass lock is exercised
    # separately against a migrated database.
    monkeypatch.setattr(
        recovery, "lock_recovery_pass", lambda engine: nullcontext(True)
    )
    monkeypatch.setattr(settings, "PURCHASE_EMAIL_DELIVERY_ENABLED", False)
    monkeypatch.setattr(settings, "LAVA_TOP_RECOVERY_MAX_LOOKUPS", 20)
    monkeypatch.setattr(settings, "LAVA_TOP_RECOVERY_REQUEST_WINDOW_SECONDS", 120)


def make_sale(db, composition="product"):
    checkout = {
        "customer_email": "private@example.com",
        "amount": Decimal("50.00"),
        "currency": "RUB",
        "payment_provider": "lava_top",
        "external_payment_id": "invoice",
    }
    if composition != "consultation":
        product = Product(
            family_slug="smartbudget",
            slug="recovery-product",
            name="SmartBudget",
            edition="Standard",
            archive_path="archives/smartbudget.zip",
            status="in_sale",
        )
        release = ProductRelease(
            product=product,
            version="1.0",
            storage_provider="cloudflare_r2",
            storage_key="product-releases/recovery/1.0.zip",
            original_filename="SmartBudget.zip",
            is_active=True,
        )
        db.add(release)
        db.flush()
        sale = create_product_sale(
            db, product=product, product_release=release, **checkout
        )
    if composition != "product":
        addon = ServiceAddon(
            code="recovery-consultation",
            name="Consultation",
            service_type="consultation",
            usage_type="standalone" if composition == "consultation" else "addon",
            family_slug="smartbudget",
            package_code="RU",
            currency_code="RUB",
            amount=Decimal("25.00"),
            is_active=True,
        )
        db.add(addon)
        db.flush()
        if composition == "consultation":
            sale = create_standalone_service_sale(
                db, service_addon_id=addon.id, service_name=addon.name, **checkout
            )
        else:
            sale.items[0].amount = Decimal("25.00")
            db.add(
                create_service_sale_item(
                    sale=sale,
                    service_addon_id=addon.id,
                    item_name=addon.name,
                    currency_code="RUB",
                    amount=addon.amount,
                )
            )
    sale.created_at = NOW - timedelta(minutes=5)
    db.flush()
    sale_id = sale.id
    db.commit()
    return sale_id


def make_pending(db, invoice, age, *, provider="lava_top"):
    db.add(
        Sale(
            customer_email="private@example.com",
            amount=50,
            currency="RUB",
            payment_status="pending",
            payment_provider=provider,
            external_payment_id=invoice,
            created_at=NOW - age,
        )
    )


def run(db, invoice=COMPLETED, *, now=NOW):
    def lookup(invoice_id):
        assert not db.in_transaction()
        return invoice

    return recovery.run_lava_top_payment_recovery(
        db, invoice_lookup=lookup, clock=lambda: now
    )


@pytest.mark.parametrize("composition", ["product", "consultation", "bundle"])
def test_recovers_and_fulfills_once(db_session, composition):
    sale_id = make_sale(db_session, composition)
    assert run(db_session)["by_outcome"] == {"recovered": 1}
    assert run(db_session)["processed"] == 0
    assert db_session.get(Sale, sale_id).payment_status == "paid"
    assert db_session.query(DownloadEntitlement).count() == (
        composition != "consultation"
    )
    assert db_session.query(ConsultationEntitlement).count() == (
        composition != "product"
    )
    assert db_session.query(PurchaseEmailDelivery).count() == 1
    assert db_session.get(LavaTopPaymentRecovery, sale_id).next_check_at is None


@pytest.mark.parametrize(
    "change",
    [
        {"invoice_id": ""},
        {"invoice_id": "other"},
        {"amount": None},
        {"amount": Decimal("50.000000000000001")},
        {"currency": None},
        {"currency": "EUR"},
        {"status": LavaTopInvoiceStatus.FAILED},
    ],
)
def test_suspicious_and_uncertain_failed_responses_park_sale(db_session, change):
    sale_id = make_sale(db_session)
    result = run(db_session, replace(COMPLETED, **change))
    outcome = (
        "review_provider_failed" if "status" in change else "review_invoice_evidence"
    )
    assert result["by_outcome"] == {outcome: 1}
    assert run(db_session, now=NOW + timedelta(days=30))["processed"] == 0
    assert db_session.get(Sale, sale_id).payment_status == "pending"
    state = db_session.get(LavaTopPaymentRecovery, sale_id)
    assert state.last_outcome == outcome
    assert state.next_check_at is None
    assert db_session.query(DownloadEntitlement).count() == 0


@pytest.mark.parametrize(
    ("age", "interval", "status"),
    [
        (timedelta(minutes=5), timedelta(minutes=5), LavaTopInvoiceStatus.NEW),
        (timedelta(hours=1), timedelta(minutes=15), LavaTopInvoiceStatus.IN_PROGRESS),
        (timedelta(days=1), timedelta(hours=1), LavaTopInvoiceStatus.NEW),
        (timedelta(days=7), timedelta(days=1), LavaTopInvoiceStatus.IN_PROGRESS),
    ],
)
def test_non_terminal_cadence(db_session, age, interval, status):
    make_pending(db_session, "invoice", age)
    db_session.commit()
    invoice = LavaTopInvoiceDetails("invoice", status)
    assert run(db_session, invoice)["by_outcome"] == {"non_terminal": 1}
    assert (
        run(db_session, invoice, now=NOW + interval - timedelta(seconds=1))["due"] == 0
    )
    assert run(db_session, invoice, now=NOW + interval)["processed"] == 1
    sale = db_session.scalar(select(Sale))
    assert sale.payment_status == "pending"
    assert sale.payment_last_checked_at is None


def test_pass_budgets_and_aged_reservation(db_session, monkeypatch):
    for index in range(24):
        make_pending(db_session, f"recent-{index}", timedelta(minutes=10 + index))
    for index in range(8):
        make_pending(db_session, f"aged-{index}", timedelta(days=15 + index))
    make_pending(db_session, "too-recent", timedelta(minutes=4))
    make_pending(db_session, "no-invoice", timedelta(days=2), provider="other")
    make_pending(db_session, "", timedelta(days=2))
    make_pending(db_session, None, timedelta(days=2))
    db_session.commit()
    called = []

    def lookup(invoice_id):
        called.append(invoice_id)
        return LavaTopInvoiceDetails(invoice_id, LavaTopInvoiceStatus.NEW)

    result = recovery.run_lava_top_payment_recovery(
        db_session, invoice_lookup=lookup, clock=lambda: NOW
    )
    assert (result["due"], result["processed"], result["deferred"]) == (32, 20, 12)
    assert result["by_age"] == {
        "recent": {"due": 24, "processed": 16, "deferred": 8},
        "aged": {"due": 8, "processed": 4, "deferred": 4},
    }
    assert sum(invoice.startswith("aged-") for invoice in called) == 4
    assert called[0] == "recent-23"
    assert called[1:5] == ["aged-7", "aged-6", "aged-5", "aged-4"]

    monkeypatch.setattr(settings, "LAVA_TOP_RECOVERY_MAX_LOOKUPS", 6)
    elapsed = iter([0, 0, 120])
    result = recovery.run_lava_top_payment_recovery(
        db_session,
        invoice_lookup=lookup,
        clock=lambda: NOW,
        elapsed_clock=lambda: next(elapsed),
    )
    assert (result["processed"], result["deferred"]) == (1, 11)
    assert result["status"] == "request_window_elapsed"


@pytest.mark.parametrize(
    ("retry_after", "delay"),
    [
        ("600", timedelta(minutes=10)),
        (
            format_datetime(NOW + timedelta(minutes=7), usegmt=True),
            timedelta(minutes=7),
        ),
        ("malformed", timedelta(minutes=15)),
        (None, timedelta(minutes=15)),
    ],
)
def test_rate_limit_stops_pass_and_pauses_other_invoices(
    db_session, monkeypatch, retry_after, delay
):
    make_pending(db_session, "invoice", timedelta(hours=1))
    make_pending(db_session, "other-invoice", timedelta(minutes=6))
    db_session.commit()
    monkeypatch.setattr(settings, "LAVA_TOP_API_KEY", "test-provider-key")
    calls = []

    def rate_limited(url, **kwargs):
        calls.append(url)
        return httpx.Response(
            429,
            request=httpx.Request("GET", url),
            headers={"Retry-After": retry_after} if retry_after is not None else {},
        )

    monkeypatch.setattr(httpx, "get", rate_limited)
    result = recovery.run_lava_top_payment_recovery(db_session, clock=lambda: NOW)
    assert result["status"] == "rate_limited"
    assert (result["due"], result["processed"], result["deferred"]) == (2, 1, 1)
    assert result["by_outcome"] == {"rate_limited": 1}
    assert len(calls) == 1
    assert (
        run(db_session, now=NOW + delay - timedelta(seconds=1))["status"] == "cooldown"
    )
    assert run(db_session, now=NOW + delay)["processed"] == 2


def test_http_408_stops_pass_and_allows_retry_after_global_cooldown(
    db_session, monkeypatch
):
    make_pending(db_session, "invoice", timedelta(minutes=10))
    make_pending(db_session, "other-invoice", timedelta(minutes=6))
    db_session.commit()
    monkeypatch.setattr(settings, "LAVA_TOP_API_KEY", "test-provider-key")
    calls = []

    def lookup(url, **kwargs):
        invoice_id = url.rsplit("/", 1)[-1]
        calls.append(invoice_id)
        request = httpx.Request("GET", url)
        if len(calls) == 1:
            return httpx.Response(408, request=request)
        return httpx.Response(
            200, json={"id": invoice_id, "status": "NEW"}, request=request
        )

    monkeypatch.setattr(httpx, "get", lookup)
    result = recovery.run_lava_top_payment_recovery(db_session, clock=lambda: NOW)
    assert result["status"] == "provider_unavailable"
    assert (result["due"], result["processed"], result["deferred"]) == (2, 1, 1)
    assert result["by_outcome"] == {"provider_unavailable": 1}
    assert calls == ["invoice"]

    expires = NOW + timedelta(minutes=5)
    with Session(db_session.get_bind()) as next_pass:
        state = next_pass.scalar(select(LavaTopPaymentRecovery))
        assert state.last_outcome == "provider_unavailable"
        assert state.next_check_at.replace(tzinfo=UTC) == expires
        cooldown = next_pass.scalar(select(LavaTopRecoveryCooldown))
        assert cooldown.until.replace(tzinfo=UTC) == expires
        next_pass.rollback()
        paused = recovery.run_lava_top_payment_recovery(
            next_pass, clock=lambda: expires - timedelta(seconds=1)
        )
        assert paused["status"] == "cooldown"
        assert paused["processed"] == 0
        assert calls == ["invoice"]
        resumed = recovery.run_lava_top_payment_recovery(
            next_pass, clock=lambda: expires
        )
        assert resumed["by_outcome"] == {"non_terminal": 2}
        assert calls.count("invoice") == 2


def test_provider_timeout_backoff_is_persisted_and_bounded(db_session, monkeypatch):
    make_pending(db_session, "invoice", timedelta(minutes=10))
    db_session.commit()
    monkeypatch.setattr(settings, "LAVA_TOP_API_KEY", "test-provider-key")

    def timeout(*args, **kwargs):
        raise httpx.ReadTimeout("secret provider diagnostics")

    monkeypatch.setattr(httpx, "get", timeout)
    now = NOW
    for minutes in (5, 10, 20, 30, 30):
        result = recovery.run_lava_top_payment_recovery(db_session, clock=lambda: now)
        assert result["by_outcome"] == {"provider_unavailable": 1}
        now += timedelta(minutes=minutes)
        assert run(db_session, now=now - timedelta(seconds=1))["status"] == "cooldown"


@pytest.mark.parametrize("receipt_amount", ["50.000000000000001", "NaN", '"invalid"'])
def test_invalid_or_inexact_provider_amount_cannot_confirm(
    db_session, monkeypatch, receipt_amount
):
    sale_id = make_sale(db_session)
    monkeypatch.setattr(settings, "LAVA_TOP_API_KEY", "test-provider-key")

    def lookup(url, **kwargs):
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            content=(
                '{"id":"invoice","status":"COMPLETED","receipt":'
                f'{{"amount":{receipt_amount},"currency":"RUB"}}}}'
            ),
        )

    monkeypatch.setattr(httpx, "get", lookup)
    result = recovery.run_lava_top_payment_recovery(db_session, clock=lambda: NOW)
    assert result["by_outcome"] == {"review_invoice_evidence": 1}
    assert db_session.get(Sale, sale_id).payment_status == "pending"


def test_webhook_winning_during_lookup_does_not_redeliver(db_session, monkeypatch):
    sale_id = make_sale(db_session)

    def lookup(invoice_id):
        assert not db_session.in_transaction()
        with Session(db_session.get_bind()) as webhook_db:
            reconcile_payment_event(
                webhook_db,
                NormalizedPaymentEvent(
                    provider="lava_top",
                    external_payment_id=invoice_id,
                    outcome=PaymentOutcome.SUCCESS,
                    amount=COMPLETED.amount,
                    currency=COMPLETED.currency,
                ),
            )
            webhook_db.commit()
        return COMPLETED

    def fail(*args, **kwargs):
        pytest.fail("Recovery must not invoke delivery for a webhook-confirmed Sale.")

    monkeypatch.setattr(recovery, "reconcile_payment_and_deliver", fail)
    result = recovery.run_lava_top_payment_recovery(
        db_session, invoice_lookup=lookup, clock=lambda: NOW
    )
    assert result["by_outcome"] == {"no_longer_pending": 1}
    assert db_session.get(Sale, sale_id).payment_status == "paid"
    assert db_session.query(DownloadEntitlement).count() == 1
    assert db_session.query(PurchaseEmailDelivery).count() == 1


def test_failed_bundle_fulfillment_rolls_back(db_session):
    sale_id = make_sale(db_session, "bundle")
    sale = db_session.get(Sale, sale_id)
    sale.items[1].service_addon.service_type = "unsupported"
    db_session.commit()
    assert run(db_session)["by_outcome"] == {"review_reconciliation": 1}
    assert db_session.get(Sale, sale_id).payment_status == "pending"
    assert db_session.query(DownloadEntitlement).count() == 0
    assert db_session.query(ConsultationEntitlement).count() == 0
    assert db_session.query(PurchaseEmailDelivery).count() == 0
    assert db_session.get(LavaTopPaymentRecovery, sale_id).next_check_at is None


def test_already_running_skips_work(db_session, monkeypatch):
    make_sale(db_session)
    monkeypatch.setattr(
        recovery, "lock_recovery_pass", lambda engine: nullcontext(False)
    )
    assert run(db_session) == {"status": "already_running", "processed": 0}
