import json

from app.core import db
from app.services import lava_top_payment_recovery_service as recovery
from scripts.recover_lava_top_payments import main


def test_cli_reports_sanitized_summary(db_session, monkeypatch, capsys):
    monkeypatch.setattr(db, "SessionLocal", lambda: db_session)
    summary = {
        "status": "completed",
        "due": 1,
        "processed": 1,
        "deferred": 0,
        "by_outcome": {"review_invoice_evidence": 1},
    }
    monkeypatch.setattr(
        recovery, "run_lava_top_payment_recovery", lambda session: summary
    )
    assert main() == 0
    output = capsys.readouterr()
    assert json.loads(output.out) == summary
    assert not output.err


def test_cli_hides_sensitive_failure(db_session, monkeypatch, capsys):
    monkeypatch.setattr(db, "SessionLocal", lambda: db_session)

    def fail(session):
        raise RuntimeError(
            "private@example.com secret-token https://example.test/private"
        )

    monkeypatch.setattr(recovery, "run_lava_top_payment_recovery", fail)
    assert main() == 1
    output = capsys.readouterr()
    assert not output.out
    assert json.loads(output.err) == {"error": "lava_top_payment_recovery_failed"}
