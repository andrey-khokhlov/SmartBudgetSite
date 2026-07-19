from dataclasses import fields
from types import SimpleNamespace

from app.services import feedback_prefill_service


def test_download_prefill_context_has_exact_customer_facing_whitelist():
    assert {
        field.name
        for field in fields(feedback_prefill_service.DownloadFeedbackPrefillContext)
    } == {
        "message_type",
        "customer_email",
        "support_reference",
        "product_name",
        "product_edition",
        "release_version",
        "purchase_date",
        "subject",
        "message",
    }


def test_download_prefill_service_uses_repository_boundary(monkeypatch):
    repository_calls = []
    entitlement = SimpleNamespace(
        sale_item=SimpleNamespace(
            sale=SimpleNamespace(
                customer_email="customer@example.com",
                created_at=None,
            ),
            product=SimpleNamespace(name="SmartBudget", edition="Standard"),
            item_name="SmartBudget purchase",
        ),
        release=SimpleNamespace(
            product=None,
            version="3.1.0",
        ),
    )

    class StubRepository:
        def __init__(self, db):
            repository_calls.append(("init", db))

        def get_by_support_reference(self, support_reference):
            repository_calls.append(("lookup", support_reference))
            return entitlement

    monkeypatch.setattr(
        feedback_prefill_service,
        "DownloadEntitlementRepository",
        StubRepository,
    )
    db = object()

    context = feedback_prefill_service.get_download_feedback_prefill_context(
        db,
        "DL-ABCDEFGH",
        "en",
    )

    assert repository_calls == [("init", db), ("lookup", "DL-ABCDEFGH")]
    assert context is not None
    assert context.customer_email == "customer@example.com"
    assert context.product_name == "SmartBudget"
    assert context.product_edition == "Standard"
    assert context.release_version == "3.1.0"


def test_download_prefill_service_rejects_unsupported_reference_before_lookup(
    monkeypatch,
):
    def fail_if_constructed(db):
        raise AssertionError("Repository must not be used for unsupported references")

    monkeypatch.setattr(
        feedback_prefill_service,
        "DownloadEntitlementRepository",
        fail_if_constructed,
    )

    context = feedback_prefill_service.get_download_feedback_prefill_context(
        object(),
        "PAY-ABCDEFGH",
        "en",
    )

    assert context is None
