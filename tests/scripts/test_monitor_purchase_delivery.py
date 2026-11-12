import json

from app.core import db
from app.models.enums import PaymentStatus
from app.models.sale import Sale
from scripts.monitor_purchase_delivery import main


def test_cli_reports_aggregate_findings(db_session, monkeypatch, capsys):
    email = "private-buyer@example.com"
    db_session.add(
        Sale(
            customer_email=email,
            amount=50,
            currency="RUB",
            payment_status=PaymentStatus.PAID,
        )
    )
    db_session.commit()
    monkeypatch.setattr(db, "SessionLocal", lambda: db_session)

    assert main() == 0
    output = capsys.readouterr()
    assert not output.err
    assert json.loads(output.out) == {
        "by_kind": {"email_record_missing": 1, "sale_items_missing": 1},
        "by_severity": {"error": 2},
        "open_incidents": 2,
        "opened": 2,
        "paid_sales_scanned": 1,
        "resolved": 0,
    }
    assert email not in output.out


def test_cli_suppresses_sensitive_operational_errors(monkeypatch, capsys):
    def fail():
        raise RuntimeError("private-buyer@example.com private-capability-token")

    monkeypatch.setattr(db, "SessionLocal", fail)
    assert main() == 1
    output = capsys.readouterr()
    assert not output.out
    assert json.loads(output.err) == {"error": "purchase_delivery_monitoring_failed"}
